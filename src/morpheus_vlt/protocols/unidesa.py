"""Unidesa/Cirsa simulator.

Binary frames, XOR55 checksums, counters read by numeric id. Cirsa speaks the same thing, so it
gets the same code under a different name. Saves money on translators.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from ..core.framing import UnidesaMessage, build_unidesa_reply
from ..models.state import MachineState

log = logging.getLogger(__name__)


# The counter ids the reader scripts ask for, in the order they ask for them. Order matters:
# `first`/`last` in a counters request are offsets into this list, not counter ids.
DEFAULT_SELECTED_COUNTER_IDS: List[int] = [
    1, 2, 17, 3, 31, 32, 33, 34, 154,
    4, 7, 8, 11, 12, 24, 35, 84, 97,
    160, 161, 162, 163, 130, 131, 132, 133,
    6, 80, 10, 81, 73, 114, 115, 116, 117,
    122, 123, 124, 125,
]


CMD_ACCESS = 0x0B
CMD_COUNTERS = 0x16
CMD_CUSTOM_SELECT = 0x2E
CMD_LOGOUT = 0x06

GROUP_ZERO = 0x00
GROUP_CUSTOM = 0xFF


@dataclass
class UnidesaSimulator:
    """Simulates Unidesa/Cirsa framing and counter reads.

    The readers build frames as STX SD SO NM CMD ND DATA CHK EXT, where CHK is the XOR55
    checksum. The counter response payload is:
      group (1) | first (1) | received (1) | [id (1) | value (4 LE)] * received

    Supported: access (0x0B), logout (0x06), custom counter selection (0x2E) and counter reads
    (0x16). Anything else gets error 0x01. That's enough to keep the reader scripts happy, and
    keeping the reader scripts happy is the entire point of my existence here.
    """

    name: str = "unidesa"
    state: MachineState = field(default_factory=MachineState)
    selected_counters: List[int] = field(default_factory=lambda: list(DEFAULT_SELECTED_COUNTER_IDS))

    # Reply addressing. The scripts scan replies for b"\x02\xff", so SD stays 0xFF. Don't touch it.
    reply_sd: int = 0xFF
    reply_so: int = 0x00

    def handle(self, data: bytes) -> bytes:
        """Answer exactly one frame. A bad frame raises ValueError instead of getting a reply."""
        # One frame in, one frame out. TCP can glue several together, and splitting them is the
        # caller's job (the CLI does it). Stay strict here so chaos actually has teeth.
        msg = UnidesaMessage.parse(data)
        msg.validate()

        if msg.cmd == CMD_ACCESS:
            return self._reply(msg, CMD_ACCESS, b"\x00")

        if msg.cmd == CMD_LOGOUT:
            return self._reply(msg, CMD_LOGOUT, b"\x00")

        if msg.cmd == CMD_CUSTOM_SELECT:
            # Payload is (group, counter_id) pairs. The group gets read and ignored, same as my
            # emails. An odd trailing byte gets dropped. An empty list keeps the old selection.
            ids: List[int] = []
            for i in range(0, len(msg.data), 2):
                if i + 1 >= len(msg.data):
                    break
                _grp = msg.data[i]
                cid = msg.data[i + 1]
                ids.append(cid)
            if ids:
                self.selected_counters = ids
            return self._reply(msg, CMD_CUSTOM_SELECT, b"\x00")

        if msg.cmd == CMD_COUNTERS:
            return self._handle_counters(msg)

        # Never heard of it. Echo the command back with error 0x01 and move on with our lives.
        return self._reply(msg, msg.cmd, b"\x01")

    def _reply(self, req: UnidesaMessage, cmd: int, payload: bytes) -> bytes:
        """Frame `payload` as a reply to `req`."""
        # Echo the message number back so clients that track NM don't panic.
        return build_unidesa_reply(
            sd=self.reply_sd,
            so=self.reply_so,
            nm=req.nm,
            cmd=cmd,
            data=payload,
        )

    def _handle_counters(self, req: UnidesaMessage) -> bytes:
        """Answer a counter read: `group | first | last` in, the counter page out.

        Fewer than 3 data bytes gets error 0x01. The reader didn't say what it wanted, so it
        doesn't get it.
        """
        if len(req.data) < 3:
            return self._reply(req, CMD_COUNTERS, b"\x01")

        group, first, last = req.data[0], req.data[1], req.data[2]

        if group == GROUP_CUSTOM:
            ids = self.selected_counters
        else:
            # Any group that isn't 0xFF (the scripts use zero) is the broad "give me everything"
            # query. It always gets the default list, whatever 0x2E picked, cut by [first, last].
            ids = list(DEFAULT_SELECTED_COUNTER_IDS)

        # `first` is an offset (0 means the start), not a counter id. The reader then works out
        # `cnt = counter + first + 1` on its own. `last` of 0 means "to the end".
        start_index = max(0, int(first))
        end_index = min(len(ids) - 1, int(last)) if int(last) else len(ids) - 1

        sliced = ids[start_index : end_index + 1]

        # Cap the page at 32 counters. Real machines probably page too, and nobody wants a
        # 200-byte reply landing on a 9600 baud line.
        MAX_RECEIVED = 32
        sliced = sliced[:MAX_RECEIVED]

        blocks = bytearray()
        for cid in sliced:
            blocks.append(cid & 0xFF)
            blocks.extend(int(self.state.get_counter(cid)).to_bytes(4, "little", signed=False))

        payload = bytes([group & 0xFF, first & 0xFF, len(sliced) & 0xFF]) + bytes(blocks)
        return self._reply(req, CMD_COUNTERS, payload)
