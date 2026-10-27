"""The thin layer between a transport and a protocol, where chaos gets its turn."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional, Protocol

from .chaos import ChaosProfile
from .framing import split_unidesa_frames

# Protocols that speak Unidesa frames and need the byte stream cut into whole frames first.
UNIDESA_FAMILY = ("unidesa", "cirsa")


class ProtocolSimulator(Protocol):
    """Anything with a `name` and a bytes-in, bytes-out `handle` qualifies. The bar is low."""

    name: str

    def handle(self, data: bytes) -> bytes:
        ...


@dataclass
class Simulator:
    """Ask the protocol for a reply, then let chaos ruin it if chaos is enabled."""

    protocol: ProtocolSimulator
    chaos: Optional[ChaosProfile] = None

    def handle(self, data: bytes) -> bytes:
        """Return the protocol's reply, possibly dropped, mangled, delayed or sent twice.

        Duplicates come back glued together in one buffer, which is exactly how they'd look
        on the wire anyway.
        """
        out = self.protocol.handle(data)
        if self.chaos and self.chaos.enabled:
            bufs = self.chaos.apply(out)
            return b"".join(bufs)
        return out


def build_handler(sim: Simulator, protocol: str) -> Callable[[bytes], bytes]:
    """Wrap `sim` in the bytes handler a transport wants. The CLI and the pytest fixture share it.

    Unidesa frames arrive however the kernel feels like delivering them: half a frame now, three
    glued together later. For that family the handler buffers the stream, cuts it into whole
    frames and answers each one. Everybody else gets their bytes as they come and buffers on
    their own.

    Either way, if the protocol blows up, the error gets logged and the reply is empty. The
    client sits there wondering, which is honestly what real hardware does, and the server
    lives to answer the next request instead of taking the whole line down with it.
    """
    log = logging.getLogger("morpheus-vlt")

    if protocol in UNIDESA_FAMILY:
        stream_buf = bytearray()

        def unidesa_handler(buf: bytes) -> bytes:
            stream_buf.extend(buf)
            out = bytearray()
            for frame in split_unidesa_frames(stream_buf):
                try:
                    out.extend(sim.handle(frame))
                except Exception:
                    log.exception("Handler error")
            return bytes(out)

        return unidesa_handler

    def handler(buf: bytes) -> bytes:
        try:
            return sim.handle(buf)
        except Exception:
            log.exception("Handler error")
            return b""

    return handler
