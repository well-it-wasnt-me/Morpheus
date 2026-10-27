"""Pytest plugin that hands your tests a fake VLT on demand.

Registered through the `pytest11` entry point, so installing the package is enough. No conftest
gymnastics, no imports, it just shows up. Like a cold.
"""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import pytest

from .core.chaos import ChaosProfile
from .core.factory import build_protocol
from .core.simulator import Simulator, build_handler
from .core.transport import PtyByteServer, PtyConfig, ServerConfig, TCPByteServer
from .models.state import MachineState

# How long the fixture waits for a server to come up before calling it dead.
READY_TIMEOUT_S = 5.0


@dataclass
class SimHandle:
    """What a test gets back: the transport, where to connect, and how to shut it up early.

    `endpoint` is "host:port" for TCP or a filesystem path for a PTY. Either way it's ready to use
    the moment you get the handle.
    """

    transport: str
    endpoint: str
    stop: Callable[[], None]


@pytest.fixture
def morpheus_vlt_server(tmp_path_factory: pytest.TempPathFactory) -> Callable[..., SimHandle]:
    """Factory fixture: call it to spin up a simulator in a background thread.

    Call it as many times as you like. It returns once the server is actually listening, so
    connect right away. Every server gets stopped and joined at teardown, so you don't have to
    remember. Port 0 picks a free port, and a PTY with no path lands in a pytest temp dir named
    ttyMORPHEUS.

    The request handling is the CLI's: Unidesa frames get cut out of the byte stream, and a
    protocol error gets logged instead of killing the server. DEX always gets the built-in
    EVA-DTS file here, there's no knob for it.
    """
    threads: list[threading.Thread] = []
    servers: list[PtyByteServer | TCPByteServer] = []

    def _find_free_port() -> int:
        # Ask the kernel for a free port, then hang up. Somebody could grab it in between.
        # Hasn't happened yet. Famous last words.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def _launch(srv: PtyByteServer | TCPByteServer, transport: str) -> None:
        thread = threading.Thread(target=srv.start, daemon=True)
        thread.start()
        threads.append(thread)
        servers.append(srv)
        if not srv.ready.wait(timeout=READY_TIMEOUT_S):
            srv.stop()
            raise RuntimeError(
                f"{transport} server didn't come up within {READY_TIMEOUT_S:.0f} s. "
                "The thread's traceback usually says why."
            )

    def _start(
        *,
        protocol: str = "unidesa",
        transport: str = "tcp",
        host: str = "127.0.0.1",
        port: int = 0,
        tty_name: Optional[str] = None,
        tty_path: Optional[str] = None,
        vdai_type: Optional[str] = None,
        sas_addr: int = 0x01,
        chaos: Optional[ChaosProfile] = None,
        state: Optional[MachineState] = None,
    ) -> SimHandle:
        if state is None:
            state = MachineState()
        proto = build_protocol(protocol, state, vdai_type, sas_addr)
        handler = build_handler(Simulator(protocol=proto, chaos=chaos), protocol)

        if transport == "pty":
            if not tty_path:
                if not tty_name:
                    tty_name = "ttyMORPHEUS"
                tty_path = str(tmp_path_factory.mktemp("pty") / tty_name)
            pty_srv = PtyByteServer(PtyConfig(link_path=tty_path), handler)
            _launch(pty_srv, "pty")
            return SimHandle(transport="pty", endpoint=tty_path, stop=pty_srv.stop)

        if port == 0:
            port = _find_free_port()
        tcp_srv = TCPByteServer(ServerConfig(host=host, port=port), handler)
        _launch(tcp_srv, "tcp")
        return SimHandle(transport="tcp", endpoint=f"{host}:{tcp_srv.cfg.port}", stop=tcp_srv.stop)

    yield _start

    # Teardown. Stop everything we started, give the threads a couple of seconds to notice.
    for srv in servers:
        srv.stop()
    for thread in threads:
        thread.join(timeout=2.0)
