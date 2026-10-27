"""Unidesa/Cirsa frame helpers.

A frame looks like `STX SD SO NM CMD ND DATA CHK EXT`. STX is 0x02, EXT is 0x03, ND is the data
length and CHK is an "XOR55" checksum, which is a byte sum wearing a 0x55 mask and calling itself
security. Eight bytes of overhead, ND bytes of payload, zero bytes of mercy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


def xor55_checksum(buf: bytes) -> int:
    """Add up every byte, XOR with 0x55, keep the low byte. That's the whole algorithm."""
    s = 0
    for b in buf:
        s += b
    return (s ^ 0x55) & 0xFF


@dataclass
class UnidesaMessage:
    """One parsed Unidesa frame, field by field, exactly as it came off the wire."""

    stx: int
    sd: int
    so: int
    nm: int
    cmd: int
    nd: int
    data: bytes
    chk: int
    ext: int

    @classmethod
    def parse(cls, raw: bytes) -> "UnidesaMessage":
        """Slice `raw` into fields. Doesn't check anything yet, that's what `validate` is for."""
        if len(raw) < 8:
            raise ValueError("frame too short")
        stx, sd, so, nm, cmd, nd = raw[:6]
        total = 8 + nd
        if len(raw) < total:
            raise ValueError("incomplete frame")
        data = raw[6:6+nd]
        chk = raw[6+nd]
        ext = raw[7+nd]
        return cls(stx, sd, so, nm, cmd, nd, data, chk, ext)

    def validate(self) -> None:
        """Raise ValueError if the delimiters are wrong or the checksum doesn't add up."""
        if self.stx != 0x02 or self.ext != 0x03:
            raise ValueError("bad STX/EXT")
        expect = xor55_checksum(bytes([self.stx, self.sd, self.so, self.nm, self.cmd, self.nd]) + self.data)
        if expect != self.chk:
            raise ValueError("checksum mismatch")


def build_unidesa_reply(sd: int, so: int, nm: int, cmd: int, data: bytes) -> bytes:
    """Wrap `data` in a complete frame with STX, length, checksum and EXT."""
    stx = 0x02
    ext = 0x03
    nd = len(data)
    hdr = bytes([stx, sd, so, nm, cmd, nd])
    chk = xor55_checksum(hdr + data)
    return hdr + data + bytes([chk, ext])


def split_unidesa_frames(buf: bytearray) -> Iterable[bytes]:
    """Yield every complete frame in `buf`, eating them as it goes.

    Garbage in front of an STX gets thrown away. A partial frame at the end stays in `buf` and
    waits for the rest to show up. TCP doesn't care where your frames end, so somebody has to.
    """
    while buf:
        # Not an STX? Not our problem anymore.
        if buf[0] != 0x02:
            del buf[0]
            continue
        if len(buf) < 6:
            return
        nd = buf[5]
        total = 8 + nd
        if len(buf) < total:
            return
        frame = bytes(buf[:total])
        del buf[:total]
        yield frame
