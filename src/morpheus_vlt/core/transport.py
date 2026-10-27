"""Byte pipes: a TCP server and a fake serial port.

Neither one knows or cares what protocol is running. Bytes come in, the handler gets called,
bytes go out. The dumbest possible design, which is why it works.
"""

from __future__ import annotations

import os
import select
import socket
import threading
import tty
from dataclasses import dataclass
import logging
from typing import Callable, Optional


# Takes whatever bytes arrived, returns whatever should go back. Empty means "say nothing".
BytesHandler = Callable[[bytes], bytes]


@dataclass
class ServerConfig:
    """Where the TCP server listens and how much it reads per gulp."""

    host: str = "127.0.0.1"
    port: int = 9000
    recv_buffer: int = 4096


@dataclass
class PtyConfig:
    """PTY settings. `link_path` is the friendly symlink, `raw` turns off the tty's opinions."""

    link_path: Optional[str] = None
    recv_buffer: int = 4096
    raw: bool = True


class TCPByteServer:
    """Minimal TCP server: request bytes in, response bytes out.

    One thread per client and no framing at all. A single recv can hold half a message or three
    of them glued together, and sorting that out is the handler's problem. `start` blocks, so run
    it in a thread if you want your terminal back.
    """

    def __init__(self, cfg: ServerConfig, handler: BytesHandler) -> None:
        self.cfg = cfg
        self.handler = handler
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        # Set once the socket is listening. Wait on it before connecting, or enjoy the race.
        self.ready = threading.Event()

    def start(self) -> None:
        """Bind, listen, and accept clients until `stop` closes the socket out from under us."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.cfg.host, self.cfg.port))
        self._sock.listen(5)
        self.ready.set()

        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                # stop() closed the socket. That's our cue to leave.
                break
            t = threading.Thread(target=self._serve_client, args=(conn,), daemon=True)
            t.start()

    def stop(self) -> None:
        """Close the listening socket. Clients already connected finish their current request."""
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _serve_client(self, conn: socket.socket) -> None:
        """Feed one client's bytes to the handler until the client hangs up."""
        with conn:
            while not self._stop.is_set():
                data = conn.recv(self.cfg.recv_buffer)
                if not data:
                    return
                resp = self.handler(data)
                if resp:
                    conn.sendall(resp)


class PtyByteServer:
    """PTY-backed byte server for serial-style clients.

    Opens a pseudo-terminal, optionally drops a symlink to it at a name you can remember, and
    serves whoever opens the other end. Your pyserial code thinks it found a real port. It didn't.
    Linux/macOS only, because Windows and PTYs have never been on speaking terms.

    When nothing arrives for 100 ms the handler gets called with b"". Most protocols shrug and
    return nothing. SAS uses it to keep announcing its address until the host shows up.
    """

    def __init__(self, cfg: PtyConfig, handler: BytesHandler) -> None:
        self.cfg = cfg
        self.handler = handler
        self._stop = threading.Event()
        # Set once the PTY exists and the symlink points at it. Open the device after that, not before.
        self.ready = threading.Event()
        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self._link_path: Optional[str] = None
        self.slave_name: Optional[str] = None

    def start(self) -> None:
        """Open the PTY, make the symlink, then pump bytes until `stop`. Blocks, like its cousin."""
        self._master_fd, self._slave_fd = os.openpty()
        self.slave_name = os.ttyname(self._slave_fd)
        if self.cfg.raw:
            tty.setraw(self._slave_fd)
        if self.cfg.link_path:
            self._link_path = self._create_link(self.cfg.link_path, self.slave_name)
        logging.getLogger("morpheus-vlt").info(
            "PTY ready: %s (link: %s)", self.slave_name, self._link_path or "none"
        )
        self.ready.set()

        while not self._stop.is_set():
            master_fd = self._master_fd
            if master_fd is None:
                break
            try:
                readable, _, _ = select.select([master_fd], [], [], 0.1)
            except OSError:
                break
            if not readable:
                # Quiet line. Give the protocol a chance to speak up unprompted.
                idle_resp = self.handler(b"")
                if idle_resp:
                    try:
                        os.write(master_fd, idle_resp)
                    except OSError:
                        break
                continue
            try:
                data = os.read(master_fd, self.cfg.recv_buffer)
            except OSError:
                break
            if not data:
                continue
            resp = self.handler(data)
            if resp:
                try:
                    os.write(master_fd, resp)
                except OSError:
                    break

    def stop(self) -> None:
        """Close both PTY ends, remove the symlink. Leave the campsite cleaner than you found it."""
        self._stop.set()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._slave_fd is not None:
            try:
                os.close(self._slave_fd)
            except OSError:
                pass
            self._slave_fd = None
        if self._link_path:
            try:
                os.unlink(self._link_path)
            except OSError:
                pass
            self._link_path = None

    @staticmethod
    def _create_link(path: str, target: str) -> str:
        """Point `path` at `target`, replacing a stale symlink but never a real file.

        If something that isn't a symlink is sitting there, raise instead of deleting it. Nobody
        wants to explain why /dev/ttyS0 vanished.
        """
        if os.path.exists(path):
            if os.path.islink(path):
                os.unlink(path)
            else:
                raise FileExistsError(f"{path} exists and is not a symlink")
        os.symlink(target, path)
        return path
