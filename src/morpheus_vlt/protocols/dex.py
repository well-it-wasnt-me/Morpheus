"""DEX/UCS simulator, playing the machine (VMC) side.

DEX is how vending machines hand over their audit data: two handshakes, then an EVA-DTS text
file sent in DLE-framed blocks with a CRC-16 on each one. It's a protocol from the days when a
handheld terminal was cutting-edge, and it has been feeling its age ever since.

The dance, from the reader's point of view:
  1. reader ENQ                     -> sim DLE0
  2. reader DLE SOH id/op/rev ...   -> sim DLE1 (or NAK if the CRC is junk)
  3. reader EOT                     -> sim ENQ (roles swap, the machine drives now)
  4. reader DLE0/DLE1               -> sim second handshake (response code, id, revision)
  5. reader DLE1                    -> sim EOT ENQ
  6. reader ACK                     -> sim first data block
  7. reader ACK / NAK               -> next block / same block again. After the last one, EOT.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum, auto

from ..models.state import MachineState

# Control bytes. The 1960s called, they want them back. Too bad.
ENQ = b"\x05"
EOT = b"\x04"
DLE = 0x10
SOH = 0x01
STX = 0x02
ETX = 0x03
ETB = 0x17
SYN = 0x16
ACK0 = bytes([DLE, 0x30])  # DLE '0'. DEX ACKs alternate between DLE0 and DLE1
ACK1 = bytes([DLE, 0x31])  # DLE '1'
NAK = b"\x15"

DLE_SOH = bytes([DLE, SOH])
DLE_STX = bytes([DLE, STX])
DLE_ETX = bytes([DLE, ETX])
DLE_ETB = bytes([DLE, ETB])

MAX_BLOCK_BYTES = 245
MAX_BLOCK_DATA = MAX_BLOCK_BYTES - 2  # the closing DLE + ETB/ETX count against the 245 too

# A first-handshake request is about 23 bytes. If a DLE SOH has been sitting in the buffer this
# long without a DLE ETX, it's not coming. Drop it and resync instead of hoarding garbage.
MAX_HANDSHAKE_BYTES = 256

DEFAULT_COMMUNICATION_ID = b"0000000001"
DEFAULT_REVISION_LEVEL = b"R01L01"
DEFAULT_RESPONSE_CODE = b"00"


def dex_crc16_update(crc: int, byte: int) -> int:
    """Feed one byte into a DEX/UCS CRC-16 (x16 + x15 + x2 + 1), one bit at a time, by hand.

    Yes, a lookup table would be faster. At 9600 baud nobody is going to notice.
    """
    for j in range(8):
        data_0 = (byte >> j) & 0x01
        bcc_0 = crc & 0x01
        bcc_1 = (crc >> 1) & 0x01
        bcc_14 = (crc >> 14) & 0x01
        x16 = bcc_0 ^ data_0
        x15 = bcc_1 ^ x16
        x2 = bcc_14 ^ x16
        crc >>= 1
        crc &= 0x5FFE
        crc |= x15
        crc |= x2 << 13
        crc |= x16 << 15
    return crc


def dex_crc16_bytes(data: bytes, *, crc: int = 0x0000, skip_dle_syn: bool = True) -> int:
    """Compute the CRC-16 over `data`, skipping DLE and SYN bytes unless told otherwise.

    It skips every 0x10, including one that's actual data and not framing. EVA-DTS files are
    printable ASCII, so that hasn't mattered yet. If it ever does, start looking here.
    """
    for byte in data:
        if skip_dle_syn and byte in (DLE, SYN):
            continue
        crc = dex_crc16_update(crc, byte)
    return crc


# The handshake fields are fixed width and DEX does not negotiate. These force whatever you pass
# into the right size: comm id is 10 (zero padded on the left), revision is 6 (space padded on
# the right), response code is 2 (zero padded on the left). Too long gets chopped, no questions.
def _normalize_ascii(value: bytes | str) -> bytes:
    if isinstance(value, bytes):
        return value
    return value.encode("ascii", errors="replace")


def _normalize_comm_id(value: bytes | str) -> bytes:
    raw = _normalize_ascii(value)
    if len(raw) < 10:
        raw = raw.rjust(10, b"0")
    return raw[:10]


def _normalize_revision(value: bytes | str) -> bytes:
    raw = _normalize_ascii(value)
    if len(raw) < 6:
        raw = raw.ljust(6, b" ")
    return raw[:6]


def _normalize_response_code(value: bytes | str) -> bytes:
    raw = _normalize_ascii(value)
    if len(raw) < 2:
        raw = raw.rjust(2, b"0")
    return raw[:2]


def _ensure_crlf(line: str) -> str:
    """EVA-DTS lines end in CRLF. Whatever the file had, they end in CRLF now."""
    line = line.rstrip("\r\n")
    return line + "\r\n"


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = text.splitlines()
    return [_ensure_crlf(line) for line in lines]


class DexState(Enum):
    """What the simulator is waiting for next. See the module docstring for the full dance."""

    WAIT_ENQ_FIRST = auto()
    WAIT_OPREQ = auto()
    WAIT_EOT_FIRST = auto()
    WAIT_ACK_SECOND = auto()
    WAIT_ACK_SECOND_CONFIRM = auto()
    WAIT_ACK_DATA_START = auto()
    WAIT_ACK_DATA = auto()


@dataclass
class DexSimulator:
    """DEX/UCS simulator (VMC side).

    Does the two handshakes and the data transfer, then resets and waits for the next reader.
    Bytes can arrive in any size chunks. Junk between messages gets thrown away. The EVA-DTS
    payload comes from a file, a list of lines, or a tiny built-in default if you gave it nothing.
    `state` is carried around for consistency with the other protocols but nothing reads it yet.
    """

    name: str = "dex"
    state: MachineState = field(default_factory=MachineState)

    communication_id: bytes = DEFAULT_COMMUNICATION_ID
    revision_level: bytes = DEFAULT_REVISION_LEVEL
    response_code: bytes = DEFAULT_RESPONSE_CODE
    evadts_lines: list[str] = field(default_factory=list)

    _rx: bytearray = field(default_factory=bytearray, init=False, repr=False)
    _state: DexState = field(default=DexState.WAIT_ENQ_FIRST, init=False, repr=False)
    _blocks: list[bytes] = field(default_factory=list, init=False, repr=False)
    _block_index: int = field(default=0, init=False, repr=False)
    _session_comm_id: bytes = field(default=DEFAULT_COMMUNICATION_ID, init=False, repr=False)
    _session_revision: bytes = field(default=DEFAULT_REVISION_LEVEL, init=False, repr=False)

    def __post_init__(self) -> None:
        self.communication_id = _normalize_comm_id(self.communication_id)
        self.revision_level = _normalize_revision(self.revision_level)
        self.response_code = _normalize_response_code(self.response_code)
        self.reset_session()
        if self.evadts_lines:
            self.load_evadts_lines(self.evadts_lines)
        else:
            self.load_default_evadts()

    def configure_identity(
        self,
        *,
        communication_id: bytes | str | None = None,
        revision_level: bytes | str | None = None,
        response_code: bytes | str | None = None,
    ) -> None:
        """Change the identity fields. None means leave it alone. Resets any session in flight."""
        if communication_id is not None:
            self.communication_id = _normalize_comm_id(communication_id)
        if revision_level is not None:
            self.revision_level = _normalize_revision(revision_level)
        if response_code is not None:
            self.response_code = _normalize_response_code(response_code)
        self.reset_session()

    def load_evadts_file(self, path: str) -> None:
        """Load the EVA-DTS payload from a text file. Bad bytes go out as '?', not as exceptions."""
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        self.load_evadts_lines(_split_lines(text))

    def load_evadts_lines(self, lines: Iterable[str]) -> None:
        """Use `lines` as the payload and pre-build the data blocks. Empty input sends one CRLF."""
        normalized = [_ensure_crlf(line) for line in lines]
        if not normalized:
            normalized = ["\r\n"]
        self.evadts_lines = normalized
        self._build_blocks()

    def load_default_evadts(self) -> None:
        """Smallest EVA-DTS file that still looks legit: header, machine id, zero vends, trailer."""
        comm_id = self.communication_id.decode("ascii", errors="replace")
        lines = [
            f"DXS*{comm_id}*VA*V0/6*1",
            "ST*001*0001",
            f"ID1*{comm_id}*Simulated*0001*Machine Name**0*6*2",
            "VA1*0*0*0*0",
            "SE*0*0001",
            "DXE*1*1",
        ]
        # SE carries the segment count, ST through SE inclusive. Count it instead of trusting the
        # placeholder above, because hardcoded counts are how you get 3 AM phone calls.
        seg_count = 1 + len(lines[2:4]) + 1
        lines[4] = f"SE*{seg_count}*0001"
        self.load_evadts_lines(lines)

    def reset_session(self) -> None:
        """Back to square one: wait for ENQ, rewind to the first block, forget the reader's id."""
        self._state = DexState.WAIT_ENQ_FIRST
        self._block_index = 0
        self._session_comm_id = self.communication_id
        self._session_revision = self.revision_level

    def handle(self, data: bytes) -> bytes:
        """Buffer `data` and run the state machine as far as it can go on what's buffered."""
        if not data:
            return b""
        self._rx.extend(data)
        out = bytearray()

        # One chunk can hold several messages, so keep stepping until nothing moves. The 1000 cap
        # is a seatbelt. If a bug ever makes the machine spin, it spins 1000 times, not forever.
        for _ in range(1000):
            progress = False

            if self._state == DexState.WAIT_ENQ_FIRST:
                if self._consume_control(ENQ):
                    out.extend(ACK0)
                    self._state = DexState.WAIT_OPREQ
                    progress = True
                else:
                    break

            elif self._state == DexState.WAIT_OPREQ:
                msg = self._consume_handshake_request()
                if msg is None:
                    break
                payload, crc_recv = msg
                crc_calc = dex_crc16_bytes(payload + bytes([ETX]), skip_dle_syn=True)
                if crc_calc == crc_recv:
                    self._update_session_from_request(payload)
                    out.extend(ACK1)
                    self._state = DexState.WAIT_EOT_FIRST
                else:
                    out.extend(NAK)
                progress = True

            elif self._state == DexState.WAIT_EOT_FIRST:
                if self._consume_control(EOT):
                    out.extend(ENQ)
                    self._state = DexState.WAIT_ACK_SECOND
                    progress = True
                else:
                    break

            elif self._state == DexState.WAIT_ACK_SECOND:
                if self._consume_ack():
                    out.extend(self._build_second_handshake())
                    self._state = DexState.WAIT_ACK_SECOND_CONFIRM
                    progress = True
                else:
                    break

            elif self._state == DexState.WAIT_ACK_SECOND_CONFIRM:
                # Only DLE1 counts here. ACKs alternate, and DLE0 was the previous one.
                if self._consume_ack(accept_ack0=False):
                    out.extend(EOT)
                    out.extend(ENQ)
                    self._state = DexState.WAIT_ACK_DATA_START
                    progress = True
                else:
                    break

            elif self._state == DexState.WAIT_ACK_DATA_START:
                if self._consume_ack():
                    out.extend(self._current_block())
                    self._state = DexState.WAIT_ACK_DATA
                    progress = True
                else:
                    break

            elif self._state == DexState.WAIT_ACK_DATA:
                outcome = self._consume_ack_or_nak()
                if outcome is None:
                    break
                if outcome == "nak":
                    # Reader didn't like that one. Same block again, no attitude.
                    out.extend(self._current_block())
                else:
                    if self._advance_block():
                        out.extend(self._current_block())
                    else:
                        out.extend(EOT)
                        self.reset_session()
                progress = True

            if not progress:
                break

        return bytes(out)

    def _build_second_handshake(self) -> bytes:
        """Response code, then the comm id and revision the reader sent us, echoed right back."""
        payload = self.response_code + self._session_comm_id + self._session_revision
        return self._build_handshake_message(payload)

    @staticmethod
    def _build_handshake_message(payload: bytes) -> bytes:
        """DLE SOH payload DLE ETX crc_lo crc_hi. The CRC covers the payload plus ETX."""
        crc = dex_crc16_bytes(payload + bytes([ETX]), skip_dle_syn=True)
        return DLE_SOH + payload + DLE_ETX + crc.to_bytes(2, "little")

    def _build_blocks(self) -> None:
        """Pre-build every data block: one per line, long lines split at MAX_BLOCK_DATA.

        Every block ends in ETB except the very last one, which ends in ETX. That's how the
        reader knows the file is over and it can stop pretending to be patient.
        """
        blocks: list[bytes] = []
        for line_index, line in enumerate(self.evadts_lines):
            data = line.encode("ascii", errors="replace")
            chunks = [data[i:i + MAX_BLOCK_DATA] for i in range(0, len(data), MAX_BLOCK_DATA)]
            if not chunks:
                chunks = [b""]
            for chunk_index, chunk in enumerate(chunks):
                is_last = (
                    line_index == len(self.evadts_lines) - 1
                    and chunk_index == len(chunks) - 1
                )
                blocks.append(self._build_data_block(chunk, is_last))
        if not blocks:
            blocks.append(self._build_data_block(b"", True))
        self._blocks = blocks
        self._block_index = 0

    @staticmethod
    def _build_data_block(data: bytes, is_last: bool) -> bytes:
        """DLE STX data DLE ETB|ETX crc. A DLE inside the data gets doubled so it isn't framing."""
        terminator = ETX if is_last else ETB
        crc = dex_crc16_bytes(data + bytes([terminator]), skip_dle_syn=True)
        stuffed = data.replace(bytes([DLE]), bytes([DLE, DLE]))
        return DLE_STX + stuffed + bytes([DLE, terminator]) + crc.to_bytes(2, "little")

    def _current_block(self) -> bytes:
        if not self._blocks:
            return self._build_data_block(b"", True)
        return self._blocks[self._block_index]

    def _advance_block(self) -> bool:
        self._block_index += 1
        return self._block_index < len(self._blocks)

    def _update_session_from_request(self, payload: bytes) -> None:
        """Remember the reader's comm id (bytes 0-9) and revision (11-16). Byte 10 is the op code.

        Too short to hold both and we fall back to our own values, rather than echo half a field.
        """
        if len(payload) >= 17:
            self._session_comm_id = payload[:10]
            self._session_revision = payload[11:17]
        else:
            self._session_comm_id = self.communication_id
            self._session_revision = self.revision_level

    def _consume_control(self, control: bytes) -> bool:
        """Eat everything up to and including `control`. Not there? Trim the junk, return False."""
        idx = self._rx.find(control)
        if idx == -1:
            self._trim_for_seq(control)
            return False
        del self._rx[:idx + len(control)]
        return True

    def _consume_ack(self, *, accept_ack0: bool = True, accept_ack1: bool = True) -> bool:
        """Eat the first acceptable ACK in the buffer. True if one was found."""
        seqs: list[bytes] = []
        if accept_ack0:
            seqs.append(ACK0)
        if accept_ack1:
            seqs.append(ACK1)
        if not seqs:
            return False
        found = self._consume_first_of(seqs)
        return found is not None

    def _consume_ack_or_nak(self) -> str | None:
        """Eat whichever of NAK, DLE0, DLE1 shows up first. Returns "ack", "nak", or None."""
        candidates: list[tuple[str, int, int]] = []
        nak_idx = self._rx.find(NAK)
        if nak_idx != -1:
            candidates.append(("nak", nak_idx, len(NAK)))
        ack0_idx = self._rx.find(ACK0)
        if ack0_idx != -1:
            candidates.append(("ack", ack0_idx, len(ACK0)))
        ack1_idx = self._rx.find(ACK1)
        if ack1_idx != -1:
            candidates.append(("ack", ack1_idx, len(ACK1)))
        if not candidates:
            self._trim_for_seq(ACK0)
            return None
        kind, idx, length = min(candidates, key=lambda x: x[1])
        del self._rx[:idx + length]
        return kind

    def _consume_first_of(self, seqs: Iterable[bytes]) -> bytes | None:
        """Eat the earliest of `seqs` found in the buffer, plus everything before it."""
        best: tuple[int, bytes] | None = None
        for seq in seqs:
            idx = self._rx.find(seq)
            if idx == -1:
                continue
            if best is None or idx < best[0]:
                best = (idx, seq)
        if best is None:
            self._trim_for_seq(ACK0)
            return None
        idx, seq = best
        del self._rx[:idx + len(seq)]
        return seq

    def _consume_handshake_request(self) -> tuple[bytes, int] | None:
        """Pull one DLE SOH ... DLE ETX crc message off the buffer as (payload, received crc).

        Returns None until the whole thing, CRC included, has arrived, and keeps the partial
        message buffered in the meantime. Slow lines deliver in pieces. Checking the CRC is the
        caller's job. This just does the unwrapping.
        """
        while True:
            start = self._rx.find(DLE_SOH)
            if start == -1:
                self._trim_for_seq(DLE_SOH)
                return None
            if start > 0:
                del self._rx[:start]
                continue
            end = self._rx.find(DLE_ETX, len(DLE_SOH))
            if end == -1:
                # The rest is still on its way. Keep what we have, unless we've been waiting for
                # an unreasonable amount of bytes, in which case this DLE SOH was a fluke.
                if len(self._rx) > MAX_HANDSHAKE_BYTES:
                    del self._rx[: len(DLE_SOH)]
                    continue
                return None
            if len(self._rx) < end + len(DLE_ETX) + 2:
                return None
            payload = bytes(self._rx[len(DLE_SOH):end])
            crc_bytes = bytes(self._rx[end + len(DLE_ETX): end + len(DLE_ETX) + 2])
            del self._rx[:end + len(DLE_ETX) + 2]
            return payload, int.from_bytes(crc_bytes, "little")

    def _trim_for_seq(self, seq: bytes) -> None:
        """Throw away the buffer, except a last byte that might be the start of `seq`.

        That one byte could be the first half of a DLE pair that got split across two reads.
        Keep it. Everything else is garbage and gets treated accordingly.
        """
        if not self._rx:
            return
        if self._rx[-1] == seq[0]:
            self._rx[:] = self._rx[-1:]
        else:
            self._rx.clear()
