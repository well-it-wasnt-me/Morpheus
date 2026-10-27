"""SAS simulator, at the "shape of the bytes" level.

Real SAS runs on a 9-bit serial line where the ninth bit marks the address byte. A PTY or a TCP
socket has eight bits and no opinion on the matter, so the electrical part is not emulated. What
is emulated: correctly sized replies, BCD meters at the offsets the readers slice, and a CRC that
saspy agrees with. The readers count bytes and cut at fixed offsets, so getting the sizes right is
90% of the job. The other 10% is also getting the sizes right.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ..models.state import MachineState

log = logging.getLogger(__name__)


CMD_SELECT_METERS = 0x0F
CMD_CUSTOM_METERS = 0x2F
CMD_EVENT_POLL = 0x80
CMD_ENABLE_BILL = 0x06
CMD_DISABLE_BILL = 0x07

DEFAULT_ASSET_NUMBER = 123456789

# AFT (0x72). The transfer code (request byte 2) says what to do with the request, the transfer
# type (byte 4) says which way the money goes. Mixing the two up is how a cash-out turns into a
# cash-in, so they get names.
AFT_CODE_FULL = 0x00  # transfer the full amount or nothing
AFT_CODE_PARTIAL = 0x01  # transfer what you can
AFT_CODE_INTERROGATE = 0xFF  # don't move anything, report the last transfer
AFT_TYPES_IN = {0x00, 0x10, 0x11}  # in-house to machine, bonus coin out, bonus jackpot
AFT_TYPES_OUT = {0x80, 0x90}  # in-house to host, win amount to host

# Commands the machine just acknowledges by echoing its address byte. Shutdown, startup, sound
# on/off, bill acceptor on/off, maintenance mode and friends. The host barks, the machine nods.
ACK_ONLY_COMMANDS = {
    0x01,
    0x02,
    0x03,
    0x04,
    0x05,
    0x06,
    0x07,
    0x08,
    0x09,
    0x0A,
    0x0B,
    0x0E,
    0x2E,
    0x7F,
    0x8A,
    0x8B,
    0x8C,
    0x94,
    0xAA,
}

# Total reply length per command, counting address, command and the 2 CRC bytes. Readers do
# `read(n)` with these exact numbers, so one byte off and they sit there until the timeout. Ack-only
# commands that also appear here never get this far, the ack wins.
FIXED_FRAME_LENGTHS = {
    0x0F: 28,
    0x10: 8,
    0x11: 8,
    0x12: 8,
    0x13: 8,
    0x14: 8,
    0x15: 8,
    0x16: 8,
    0x17: 8,
    0x18: 8,
    0x19: 24,
    0x1A: 8,
    0x1B: 24,
    0x1C: 36,
    0x1E: 28,
    0x1F: 24,
    0x20: 8,
    0x21: 6,
    0x2A: 8,
    0x2B: 8,
    0x2C: 8,
    0x2D: 8,
    0x2F: 57,
    0x31: 8,
    0x32: 8,
    0x33: 8,
    0x34: 8,
    0x35: 8,
    0x36: 8,
    0x37: 8,
    0x38: 8,
    0x39: 8,
    0x3A: 8,
    0x3B: 8,
    0x3C: 8,
    0x3D: 13,
    0x3E: 8,
    0x3F: 8,
    0x40: 8,
    0x41: 8,
    0x42: 8,
    0x43: 8,
    0x44: 8,
    0x45: 8,
    0x46: 8,
    0x47: 8,
    0x48: 10,
    0x49: 8,
    0x4A: 8,
    0x4C: 11,
    0x4D: 35,
    0x4F: 11,
    0x50: 14,
    0x51: 6,
    0x52: 22,
    0x53: 26,
    0x54: 20,
    0x55: 6,
    0x56: 8,
    0x57: 10,
    0x58: 5,
    0x6E: 10,
    0x6F: 64,
    0x70: 20,
    0x71: 20,
    0x72: 82,
    0x73: 34,
    0x74: 40,
    0x75: 8,
    0x76: 8,
    0x7B: 15,
    0x7C: 8,
    0x7D: 8,
    0x7E: 11,
    0x80: 5,
    0x83: 10,
    0x84: 11,
    0x85: 11,
    0x86: 5,
    0x87: 13,
    0x8B: 5,
    0x8C: 5,
    0x8E: 10,
    0x8F: 13,
    0x90: 14,
    0x95: 10,
    0x96: 10,
    0x97: 10,
    0x98: 10,
    0x99: 22,
    0x9A: 18,
    0xA0: 12,
    0xA4: 8,
    0xA8: 5,
    0xAF: 64,
    0xB0: 5,
    0xB1: 5,
    0xB2: 7,
    0xB3: 5,
    0xB4: 16,
    0xB5: 32,
    0xFF: 8,
}

# Commands that return one 4-byte BCD meter. Each maps to a list of meter names to try in order,
# first one present in the state wins. So "play" can stand in for "coin_in" when you only bothered
# setting one of them. I only ever bother setting one of them.
SINGLE_METER_COMMANDS = {
    0x10: ("cancelled_credits",),
    0x11: ("play", "coin_in"),
    0x12: ("win", "coin_out"),
    0x13: ("drop",),
    0x14: ("jackpot",),
    0x15: ("plays",),
    0x16: ("won",),
    0x17: ("lost",),
    0x1A: ("credits",),
    0x20: ("bill_value_total", "bill_in"),
    0x2A: ("true_coin_in", "coin_in", "play"),
    0x2B: ("true_coin_out", "coin_out", "win"),
    0x2C: ("hopper_level", "coin_hopper"),
    0x2D: ("hand_paid_cancelled_credit",),
    0x31: ("bill_1",),
    0x32: ("bill_2",),
    0x33: ("bill_5",),
    0x34: ("bill_10",),
    0x35: ("bill_20",),
    0x36: ("bill_50",),
    0x37: ("bill_100",),
    0x38: ("bill_500",),
    0x39: ("bill_1000",),
    0x3A: ("bill_200",),
    0x3B: ("bill_25",),
    0x3C: ("bill_2000",),
    0x3E: ("bill_2500",),
    0x3F: ("bill_5000",),
    0x40: ("bill_10000",),
    0x41: ("bill_20000",),
    0x42: ("bill_25000",),
    0x43: ("bill_50000",),
    0x44: ("bill_100000",),
    0x45: ("bill_250",),
    0x46: ("bill_credit_total",),
    0x47: ("coin_external",),
    0x49: ("bills_in_stacker",),
    0x4A: ("bills_stacker_credit_total",),
}

# Not magic and not a seed: it's the CRC-CCITT polynomial 0x1021, bit-reversed. The name stays
# because renaming things is a code change, and this was a comment job.
_MAGIC_SEED = 0x8408
# Built on first use, then cached. 256 entries, nobody's running out of RAM.
_SAS_CRC_TABLE: tuple[int, ...] = ()


def _build_crc_table() -> tuple[int, ...]:
    """Precompute the reflected CRC-16 lookup table, one entry per possible byte value."""
    table: list[int] = []
    for i in range(256):
        val = i
        for _ in range(8):
            if val & 0x0001:
                val = (val >> 1) ^ _MAGIC_SEED
            else:
                val >>= 1
        table.append(val & 0xFFFF)
    return tuple(table)


def _sas_crc(payload: bytes) -> tuple[int, int]:
    """CRC-16 over `payload`, returned as the two bytes in wire order: low byte first."""
    global _SAS_CRC_TABLE
    if not _SAS_CRC_TABLE:
        _SAS_CRC_TABLE = _build_crc_table()

    crc = 0
    for c in payload:
        q = crc ^ c
        crc = ((crc >> 8) ^ _SAS_CRC_TABLE[q & 0x00FF]) & 0xFFFF

    # saspy's Crc.calculate defaults to LITTLE_ENDIAN and swaps the bytes. So swap, then split
    # high/low, which puts the original low byte first. Two wrongs making a right, as usual.
    crc = ((crc & 0xFF00) >> 8) | ((crc & 0x00FF) << 8)
    return (crc >> 8) & 0xFF, crc & 0xFF


def _encode_digits(value: int, length: int) -> bytes:
    """Pack `value` as `length` bytes of BCD, two decimal digits per byte.

    1234 in 4 bytes comes out as 00 00 12 34. Negative becomes 0. Too big keeps only the low
    digits, same as a real meter rolling over. The trick: format in decimal, then read each pair
    of digits back as hex. Cheap, ugly, works.
    """
    value = max(0, int(value))
    digits = f"{value:0{length * 2}d}"[-(length * 2) :]
    out = bytearray()
    for i in range(0, len(digits), 2):
        out.append(int(digits[i : i + 2], 16))
    return bytes(out)


def _decode_digits(buf: bytes) -> int:
    """Undo `_encode_digits`. Not valid BCD? Read it as plain hex instead of dying about it."""
    if not buf:
        return 0
    hex_digits = buf.hex()
    try:
        return int(hex_digits)
    except ValueError:
        return int(hex_digits, 16)


@dataclass
class SASSimulator:
    """SAS protocol-shape simulator for serial readers.

    One request in, one reply out, no buffering. Meters come out of `state.meters`, mostly as BCD.
    AFT transfers actually move the "credits" meter, so a test can push money in and watch it
    land. Everything else is read-only and boringly consistent, which is the dream.
    """

    name: str = "sas"
    state: MachineState = field(default_factory=MachineState)
    addr: int = 0x01

    # Until the host says something, the address byte goes out on every idle tick, at most once
    # per this many seconds. The first real request shuts that off for good.
    idle_announce_interval: float = 0.50
    _announce_address_until_activity: bool = True
    _last_idle_announce: float = 0.0
    _aft_registered: bool = False
    # Last AFT transfer as (type, cashable, restricted, nonrestricted). Status polls report it.
    _last_aft: tuple[int, int, int, int] = (0x00, 0, 0, 0)
    # Fifteen spaces and an exclamation mark. Somebody's idea of a placeholder transaction ID.
    _last_transaction_id: bytes = field(
        default_factory=lambda: bytes.fromhex("20202020202020202020202020202021")
    )

    def handle(self, data: bytes) -> bytes:
        """Answer one SAS request. Empty `data` means the line is idle (see the PTY transport)."""
        if not data:
            return self._idle_address_broadcast()

        self._announce_address_until_activity = False
        req = self._strip_host_prefix(data)
        if not req:
            return b""

        cmd = req[0]

        # General poll. Answer 0x00, "no events", which is the most honest thing a machine says.
        if cmd in (CMD_EVENT_POLL, (CMD_EVENT_POLL + self.addr) & 0xFF):
            return b"\x00"

        if cmd in ACK_ONLY_COMMANDS:
            return bytes([self.addr & 0xFF])

        if cmd == CMD_SELECT_METERS:
            return self._reply_select_meters()

        if cmd == CMD_CUSTOM_METERS:
            return self._reply_custom_meters()

        if cmd in SINGLE_METER_COMMANDS:
            return self._reply_single_meter(cmd)

        if cmd == 0x18:
            return self._reply_powerup_meters()

        if cmd == 0x19:
            return self._reply_meters_11_15()

        if cmd == 0x1C:
            return self._reply_meters_1c()

        if cmd == 0x1E:
            return self._reply_bill_meters()

        if cmd == 0x1F:
            return self._reply_gaming_machine_id()

        if cmd == 0x1B:
            return self._reply_handpay_info()

        if cmd == 0x21:
            return self._reply_rom_signature()

        if cmd == 0x3D:
            return self._reply_cashout_ticket_info()

        if cmd == 0x48:
            return self._reply_last_accepted_bill_info()

        if cmd == 0x4C:
            return self._reply_secure_validation_id()

        if cmd == 0x4D:
            return self._reply_enhanced_validation_info()

        if cmd == 0x4F:
            return self._reply_current_hopper_status()

        if cmd == 0x50:
            return self._reply_validation_meters(req)

        if cmd == 0x51:
            return self._reply_total_games()

        if cmd == 0x52:
            return self._reply_game_meters(req)

        if cmd == 0x53:
            return self._reply_game_configuration(req)

        if cmd == 0x54:
            return self._reply_sas_version_serial()

        if cmd == 0x55:
            return self._reply_selected_game()

        if cmd == 0x56:
            return self._reply_enabled_games()

        if cmd == 0x57:
            return self._reply_pending_cashout_info()

        if cmd == 0x58:
            return self._reply_receive_validation_number()

        if cmd == 0x6E:
            return self._reply_authentication_info()

        if cmd == 0x70:
            return self._reply_ticket_validation_data()

        if cmd == 0x71:
            return self._reply_redeem_ticket_response()

        if cmd == 0x72:
            return self._reply_aft(req)

        if cmd == 0x73:
            return self._reply_aft_register(req)

        if cmd == 0x74:
            return self._reply_aft_lock_status(req)

        if cmd == 0x7B:
            return self._reply_extended_validation_status()

        if cmd == 0x7E:
            return self._reply_current_datetime()

        if cmd == 0xA0:
            return self._reply_enabled_features(req)

        if cmd == 0x9A:
            return self._reply_legacy_bonus_meters(req)

        return self._reply_default(cmd)

    def _strip_host_prefix(self, data: bytes) -> bytes:
        """Peel off the wake-up marker and our address so the command byte is first.

        No ninth bit on a PTY, so readers fake it with an 0x80 or 0x82 byte up front. Accepted
        shapes: [0x80|0x82, addr, cmd...], [0x82, cmd...], [addr, cmd...], or just [cmd...].
        """
        buf = bytearray(data)
        addr = self.addr & 0xFF

        if len(buf) >= 2 and buf[0] in (0x80, 0x82) and buf[1] == addr:
            buf = buf[1:]
        if buf and buf[0] == 0x82:
            buf = buf[1:]
        if buf and buf[0] == addr:
            buf = buf[1:]
        return bytes(buf)

    def _idle_address_broadcast(self) -> bytes:
        """Send our address byte on a quiet line, rate limited, until the host speaks up."""
        if not self._announce_address_until_activity:
            return b""
        now = time.monotonic()
        if now - self._last_idle_announce < self.idle_announce_interval:
            return b""
        self._last_idle_announce = now
        return bytes([self.addr & 0xFF])

    def _frame(self, cmd: int, payload: bytes = b"", total_len: int | None = None) -> bytes:
        """Build `addr cmd payload crc_lo crc_hi`.

        With `total_len`, the payload gets zero padded or chopped so the whole frame is exactly
        that long. The reader asked for N bytes, it gets N bytes. Customer service.
        """
        if total_len is not None:
            payload_len = max(0, total_len - 4)
            if len(payload) < payload_len:
                payload = payload + bytes(payload_len - len(payload))
            elif len(payload) > payload_len:
                payload = payload[:payload_len]

        body = bytes([self.addr & 0xFF, cmd & 0xFF]) + payload
        crc_hi, crc_lo = _sas_crc(body)
        return body + bytes([crc_hi, crc_lo])

    def _meter(self, *names: str) -> int:
        """Value of the first meter in `names` that exists in the state. None of them? 0."""
        for name in names:
            if name in self.state.meters:
                return int(self.state.meters[name])
        if names:
            return int(self.state.get_meter(names[0]))
        return 0

    def _reply_default(self, cmd: int) -> bytes:
        """Unknown command: 0xFF then zeros, at the expected length, or 8 if it's a total stranger.

        Not a real answer, but it's the right size, and with these readers that's most of the war.
        """
        total_len = FIXED_FRAME_LENGTHS.get(cmd, 8)
        payload = b"\xFF"
        return self._frame(cmd, payload, total_len=total_len)

    def _reply_single_meter(self, cmd: int) -> bytes:
        """One 4-byte BCD meter, picked through SINGLE_METER_COMMANDS."""
        meter_names = SINGLE_METER_COMMANDS[cmd]
        value = self._meter(*meter_names)
        payload = bytearray(4)
        payload[0:4] = _encode_digits(value, 4)
        return self._frame(cmd, bytes(payload), total_len=FIXED_FRAME_LENGTHS[cmd])

    def _reply_select_meters(self) -> bytes:
        """0x0F: cancelled credits, coin in, coin out, drop, jackpot, games played. 28 bytes."""
        payload = bytearray(24)
        payload[0:4] = _encode_digits(self._meter("cancelled_credits"), 4)
        payload[4:8] = _encode_digits(self._meter("play", "coin_in"), 4)
        payload[8:12] = _encode_digits(self._meter("win", "coin_out"), 4)
        payload[12:16] = _encode_digits(self._meter("drop"), 4)
        payload[16:20] = _encode_digits(self._meter("jackpot"), 4)
        payload[20:24] = _encode_digits(self._meter("plays"), 4)
        return self._frame(CMD_SELECT_METERS, bytes(payload), total_len=28)

    def _reply_custom_meters(self) -> bytes:
        """0x2F: ten (meter code, 4-byte BCD value) blocks, always the same ten. 57 bytes.

        The request says which meters it wants. This ignores that and sends the ten the reader
        always asks for anyway. If the reader ever changes its mind, this will be the last to know.
        """
        codes = [0, 1, 5, 6, 8, 9, 10, 11, 88, 110]
        mapping = {
            0: ("play",),
            1: ("win",),
            5: ("plays",),
            6: ("won",),
            8: ("coin_in", "play"),
            9: ("coin_out", "win"),
            10: ("coin_hopper",),
            11: ("bill_in",),
            88: ("bill_hopper",),
            110: ("bill_out",),
        }

        payload = bytearray(53)
        payload[0:3] = b"\x34\x00\x00"  # length 0x34 (52 bytes follow), then game number 0000
        idx = 3
        for code in codes:
            payload[idx] = code & 0xFF
            idx += 1
            payload[idx : idx + 4] = _encode_digits(self._meter(*mapping[code]), 4)
            idx += 4
        return self._frame(CMD_CUSTOM_METERS, bytes(payload), total_len=57)

    def _reply_powerup_meters(self) -> bytes:
        """0x18: games since last power up, then games since the slot door closed. 2 BCD bytes each."""
        payload = bytearray(4)
        payload[0:2] = _encode_digits(self._meter("games_last_power_up"), 2)
        payload[2:4] = _encode_digits(self._meter("games_since_door_closure"), 2)
        return self._frame(0x18, bytes(payload), total_len=8)

    def _reply_meters_11_15(self) -> bytes:
        """0x19: five 4-byte BCD totals. 24 bytes."""
        payload = bytearray(20)
        payload[0:4] = _encode_digits(self._meter("play"), 4)
        payload[4:8] = _encode_digits(self._meter("win"), 4)
        payload[8:12] = _encode_digits(self._meter("coin_in", "play"), 4)
        payload[12:16] = _encode_digits(self._meter("jackpot"), 4)
        payload[16:20] = _encode_digits(self._meter("plays"), 4)
        return self._frame(0x19, bytes(payload), total_len=24)

    def _reply_meters_1c(self) -> bytes:
        """0x1C: the eight big totals, door opens and power resets included. 36 bytes."""
        payload = bytearray(32)
        payload[0:4] = _encode_digits(self._meter("play"), 4)
        payload[4:8] = _encode_digits(self._meter("win"), 4)
        payload[8:12] = _encode_digits(self._meter("drop"), 4)
        payload[12:16] = _encode_digits(self._meter("jackpot"), 4)
        payload[16:20] = _encode_digits(self._meter("plays"), 4)
        payload[20:24] = _encode_digits(self._meter("won"), 4)
        payload[24:28] = _encode_digits(self._meter("slot_door_opened"), 4)
        payload[28:32] = _encode_digits(self._meter("power_reset"), 4)
        return self._frame(0x1C, bytes(payload), total_len=36)

    def _reply_bill_meters(self) -> bytes:
        """0x1E: bill counts for 1, 5, 10, 20, 50 and 100. 28 bytes."""
        payload = bytearray(24)
        payload[0:4] = _encode_digits(self._meter("bill_1"), 4)
        payload[4:8] = _encode_digits(self._meter("bill_5"), 4)
        payload[8:12] = _encode_digits(self._meter("bill_10"), 4)
        payload[12:16] = _encode_digits(self._meter("bill_20"), 4)
        payload[16:20] = _encode_digits(self._meter("bill_50"), 4)
        payload[20:24] = _encode_digits(self._meter("bill_100"), 4)
        return self._frame(0x1E, bytes(payload), total_len=28)

    def _reply_handpay_info(self) -> bytes:
        """0x1B: handpay info, for when the machine owes more than it's willing to pay itself."""
        payload = bytearray(20)
        payload[0] = self._meter("progressive_group") & 0xFF
        payload[1] = self._meter("progressive_level") & 0xFF
        payload[2:7] = _encode_digits(self._meter("handpay_amount"), 5)
        payload[7:9] = _encode_digits(self._meter("handpay_partial_amount"), 2)
        payload[9] = self._meter("handpay_reset_id") & 0xFF
        return self._frame(0x1B, bytes(payload), total_len=24)

    def _reply_rom_signature(self) -> bytes:
        """0x21: ROM signature, 2 bytes big endian. Whatever you put in rom_signature. No math."""
        sig = self._meter("rom_signature")
        payload = int(sig & 0xFFFF).to_bytes(2, "big", signed=False)
        return self._frame(0x21, payload, total_len=6)

    def _reply_cashout_ticket_info(self) -> bytes:
        """0x3D: last cashout ticket number and amount."""
        payload = bytearray(9)
        payload[0:4] = _encode_digits(self._meter("cashout_ticket_number", "ticket_number"), 4)
        payload[4:9] = _encode_digits(
            self._meter("cashout_amount_cents", "pending_cashout_amount", "credits"), 5
        )
        return self._frame(0x3D, bytes(payload), total_len=13)

    def _reply_last_accepted_bill_info(self) -> bytes:
        """0x48: country code, denomination and count of the last bill the machine swallowed."""
        payload = bytearray(6)
        payload[0] = self._meter("bill_country_code") & 0xFF
        payload[1] = self._meter("bill_last_denomination") & 0xFF
        payload[2:6] = _encode_digits(self._meter("bill_last_count"), 4)
        return self._frame(0x48, bytes(payload), total_len=10)

    def _reply_secure_validation_id(self) -> bytes:
        """0x4C: validation machine id and sequence number. The request gets ignored."""
        payload = bytearray(7)
        payload[0:3] = _encode_digits(self._meter("validation_machine_id"), 3)
        payload[3:7] = _encode_digits(self._meter("validation_sequence"), 4)
        return self._frame(0x4C, bytes(payload), total_len=11)

    def _reply_enhanced_validation_info(self) -> bytes:
        """0x4D: one enhanced validation record, every field straight out of validation_* meters."""
        payload = bytearray(31)
        payload[0] = self._meter("validation_type") & 0xFF
        payload[1] = self._meter("validation_index") & 0xFF
        payload[2:6] = _encode_digits(self._meter("validation_date"), 4)
        payload[6:9] = _encode_digits(self._meter("validation_time"), 3)
        payload[9:17] = _encode_digits(self._meter("validation_number"), 8)
        payload[17:22] = _encode_digits(self._meter("validation_amount"), 5)
        payload[22:24] = _encode_digits(self._meter("validation_ticket_number"), 2)
        payload[24] = self._meter("validation_system_id") & 0xFF
        payload[25:29] = _encode_digits(self._meter("validation_expiration"), 4)
        payload[29:31] = _encode_digits(self._meter("validation_pool_id"), 2)
        return self._frame(0x4D, bytes(payload), total_len=35)

    def _reply_current_hopper_status(self) -> bytes:
        """0x4F: hopper status, how full it is in percent, and the coin level."""
        payload = bytearray(7)
        payload[0] = 0x06  # length byte: status + percent + 4 bytes of level
        payload[1] = self._meter("hopper_status") & 0xFF
        payload[2] = self._meter("hopper_percent") & 0xFF
        payload[3:7] = _encode_digits(self._meter("hopper_level", "coin_hopper"), 4)
        return self._frame(0x4F, bytes(payload), total_len=11)

    def _reply_validation_meters(self, req: bytes) -> bytes:
        """0x50: validation count and total amount. Echoes the validation type it was asked for."""
        payload = bytearray(10)
        payload[0] = req[1] if len(req) > 1 else 0x00
        payload[1:5] = _encode_digits(self._meter("validation_total"), 4)
        payload[5:10] = _encode_digits(self._meter("validation_cumulative_amount"), 5)
        return self._frame(0x50, bytes(payload), total_len=14)

    def _reply_gaming_machine_id(self) -> bytes:
        """0x1F: who the machine claims to be. Hardcoded, because the machine is also fake."""
        payload = bytearray(20)
        payload[0:2] = b"GM"  # game id
        payload[2:5] = b"001"  # additional id
        payload[5] = 0x01  # denom code -> 0.01
        payload[6] = 0x64  # max bet, 100
        payload[7] = 0x00  # progressive group, none
        payload[8:10] = b"\x00\x00"  # game options
        payload[10:16] = b"P00001"  # paytable id
        payload[16:20] = b"9500"  # base payback, 95.00%. The house thanks you
        return self._frame(0x1F, bytes(payload), total_len=24)

    def _reply_total_games(self) -> bytes:
        """0x51: number of games on the machine. At least 1, an empty cabinet is just furniture."""
        payload = _encode_digits(max(1, self._meter("total_games")), 2)
        return self._frame(0x51, payload, total_len=6)

    def _reply_game_meters(self, req: bytes) -> bytes:
        """0x52: meters for game N. Every game reports the machine-wide meters. Lazy, but fair."""
        if len(req) >= 3:
            game_number = _decode_digits(req[1:3]) or 1
        else:
            game_number = max(1, self._meter("selected_game"))

        payload = bytearray(18)
        payload[0:2] = _encode_digits(game_number, 2)
        payload[2:6] = _encode_digits(self._meter("play"), 4)
        payload[6:10] = _encode_digits(self._meter("win"), 4)
        payload[10:14] = _encode_digits(self._meter("jackpot"), 4)
        payload[14:18] = _encode_digits(self._meter("plays"), 4)
        return self._frame(0x52, bytes(payload), total_len=22)

    def _reply_game_configuration(self, req: bytes) -> bytes:
        """0x53: game N configuration. Same fake identity as 0x1F, with the game number in front."""
        payload = bytearray(22)
        if len(req) >= 3:
            payload[0:2] = req[1:3]
        else:
            payload[0:2] = _encode_digits(max(1, self._meter("selected_game")), 2)
        payload[2:4] = b"GM"
        payload[4:7] = b"001"
        payload[7] = 0x01
        payload[8] = 0x64
        payload[9] = 0x00
        payload[10:12] = b"\x00\x00"
        payload[12:18] = b"P00001"
        payload[18:22] = b"9500"
        return self._frame(0x53, bytes(payload), total_len=26)

    def _reply_sas_version_serial(self) -> bytes:
        """0x54: SAS version and serial number. Version 6.03, serial SIM000000001."""
        payload = bytearray(16)
        payload[0] = 0x00
        payload[1:4] = b"\x00\x06\x03"  # 6.03, packed so a hex dump reads 000603
        payload[4:16] = b"SIM000000001"
        return self._frame(0x54, bytes(payload), total_len=20)

    def _reply_selected_game(self) -> bytes:
        """0x55: the game currently selected. Defaults to game 1."""
        payload = _encode_digits(max(1, self._meter("selected_game")), 2)
        return self._frame(0x55, payload, total_len=6)

    def _reply_enabled_games(self) -> bytes:
        """0x56: enabled games. There's exactly one, and it's the selected one."""
        selected = _encode_digits(max(1, self._meter("selected_game")), 2)
        payload = bytearray(4)
        payload[0] = 0x03  # length: the count byte plus 2 bytes of game number
        payload[1] = 0x01  # one enabled game. Small casino
        payload[2:4] = selected
        return self._frame(0x56, bytes(payload), total_len=8)

    def _reply_pending_cashout_info(self) -> bytes:
        """0x57: pending cashout type and amount."""
        payload = bytearray(6)
        payload[0] = self._meter("pending_cashout_type") & 0xFF
        payload[1:6] = _encode_digits(self._meter("pending_cashout_amount", "credits"), 5)
        return self._frame(0x57, bytes(payload), total_len=10)

    def _reply_receive_validation_number(self) -> bytes:
        """0x58: status 0x00, accepted. The number itself goes straight in the trash."""
        payload = bytes([0x00])
        return self._frame(0x58, payload, total_len=5)

    def _reply_authentication_info(self) -> bytes:
        """0x6E: authentication info. One component, nothing to authenticate. Trust me."""
        payload = bytearray(6)
        payload[0] = 0x01  # one installed component
        payload[1] = 0x00
        payload[2:6] = b"\x00\x00\x00\x00"
        return self._frame(0x6E, bytes(payload), total_len=10)

    def _reply_ticket_validation_data(self) -> bytes:
        """0x70: data for the ticket being redeemed, straight from the ticket_* meters."""
        payload = bytearray(16)
        payload[0] = 0x0F  # bytes following this length field
        payload[1] = self._meter("ticket_status") & 0xFF
        payload[2:7] = _encode_digits(self._meter("ticket_amount", "pending_cashout_amount"), 5)
        payload[7] = self._meter("ticket_parsing_code") & 0xFF
        payload[8:16] = _encode_digits(self._meter("ticket_validation_number"), 8)
        return self._frame(0x70, bytes(payload), total_len=20)

    def _reply_redeem_ticket_response(self) -> bytes:
        """0x71: redeem ticket. Status 0x00, it worked. No credits actually move, it's a demo."""
        payload = bytearray(16)
        payload[0] = 0x0F  # bytes following this length field
        payload[1] = 0x00  # machine status
        payload[2:7] = _encode_digits(self._meter("ticket_amount", "pending_cashout_amount"), 5)
        payload[7] = self._meter("ticket_parsing_code") & 0xFF
        payload[8:16] = _encode_digits(self._meter("ticket_validation_number"), 8)
        return self._frame(0x71, bytes(payload), total_len=20)

    def _reply_aft(self, req: bytes) -> bytes:
        """0x72: AFT transfer. The one command here that changes state.

        Request byte 2 is the transfer code, byte 4 the transfer type. A full or partial transfer
        (code 0x00 or 0x01) moves the cashable amount: types 0x00, 0x10 and 0x11 add it to
        "credits", 0x80 and 0x90 take it out (floored at zero, the machine doesn't do loans).
        Any other code, like the 0xFF status poll, moves nothing and reports the last transfer,
        which is where the readers look for the amount that actually moved. The reply always
        says the transfer succeeded, which is more than most banks will do for you.
        """
        payload = bytearray(78)

        transfer_code = req[2] if len(req) > 2 else AFT_CODE_INTERROGATE
        if transfer_code in (AFT_CODE_FULL, AFT_CODE_PARTIAL) and len(req) >= 20:
            transfer_type = req[4]
            cashable = _decode_digits(req[5:10])
            restricted = _decode_digits(req[10:15])
            nonrestricted = _decode_digits(req[15:20])

            credits = self._meter("credits")
            if transfer_type in AFT_TYPES_IN:
                credits += cashable
            elif transfer_type in AFT_TYPES_OUT:
                credits = max(0, credits - cashable)
            self.state.set_meter("credits", credits)
            self._last_aft = (transfer_type, cashable, restricted, nonrestricted)

        # Whatever happened, the reply describes the last real transfer. Before the first one,
        # that's a whole lot of zeros.
        transfer_type, cashable, restricted, nonrestricted = self._last_aft

        # Look for the transaction ID length byte at offset 60, then 45 (where it sits in the
        # request the tests build). First plausible hit wins and gets remembered. No hit means
        # this is a status poll, so report the last ID we saw.
        tx = self._last_transaction_id
        for tx_len_idx in (60, 45):
            if len(req) <= tx_len_idx:
                continue
            tx_len = req[tx_len_idx]
            if 0 < tx_len <= 32 and len(req) >= (tx_len_idx + 1 + tx_len):
                tx = bytes(req[tx_len_idx + 1 : tx_len_idx + 1 + tx_len])
                self._last_transaction_id = tx
                break

        tx_len = min(len(tx), 32)
        tx = tx[:tx_len]

        payload[1] = 0x00  # transaction buffer position
        payload[2] = 0x00  # transfer status: successful
        payload[3] = 0xFF  # receipt status: none
        payload[4] = transfer_type & 0xFF
        payload[5:10] = _encode_digits(cashable, 5)
        payload[10:15] = _encode_digits(restricted, 5)
        payload[15:20] = _encode_digits(nonrestricted, 5)
        payload[20] = 0x00
        payload[21:25] = self._asset_number_bytes()
        payload[25] = tx_len
        payload[26 : 26 + tx_len] = tx

        # Transaction date/time right after the ID, as BCD MMDDYYYYHHMMSS. Real clock, fake money.
        now_digits = time.strftime("%m%d%Y%H%M%S", time.localtime())
        now_bytes = bytes(int(now_digits[i : i + 2], 16) for i in range(0, 14, 2))
        end = min(len(payload), 26 + tx_len + len(now_bytes))
        payload[26 + tx_len : end] = now_bytes[: max(0, end - (26 + tx_len))]
        return self._frame(0x72, bytes(payload), total_len=82)

    def _reply_aft_register(self, req: bytes) -> bytes:
        """0x73: AFT registration. Code 0x80 unregisters, anything else registers. No paperwork."""
        reg_code = req[2] if len(req) > 2 else 0xFF
        if reg_code == 0x80:
            self._aft_registered = False
        else:
            self._aft_registered = True

        status = 0x01 if self._aft_registered else 0x80
        payload = bytearray(30)
        payload[2:6] = bytes([0x00, 0x00, 0x00, status])
        payload[6:26] = b"\x00" * 20
        payload[26:30] = b"POS1"
        return self._frame(0x73, bytes(payload), total_len=34)

    def _reply_aft_lock_status(self, req: bytes) -> bytes:
        """0x74: AFT lock and status. Lock code 0x80 reports 0xFF (not locked), else 0x00 (locked).

        The current credits go in the cashable slot. The other balances are always zero.
        """
        lock_code = req[1] if len(req) > 1 else 0x00
        lock_status = 0xFF if lock_code == 0x80 else 0x00

        payload = bytearray(36)
        payload[1:5] = self._asset_number_bytes()
        payload[5] = lock_status
        payload[6] = 0x00
        payload[7] = 0x00
        payload[8] = 0x00
        payload[9] = 0x01
        payload[10:15] = _encode_digits(self._meter("credits"), 5)
        payload[15:20] = _encode_digits(0, 5)
        payload[20:25] = _encode_digits(0, 5)
        payload[25:28] = _encode_digits(0, 3)
        payload[28:30] = _encode_digits(0, 2)
        return self._frame(0x74, bytes(payload), total_len=40)

    def _reply_extended_validation_status(self) -> bytes:
        """0x7B: extended validation status. Asset number plus the two ticket expirations."""
        payload = bytearray(11)
        payload[0] = 0x08
        payload[1:5] = self._asset_number_bytes()
        payload[5:7] = b"\x00\x00"
        payload[7:9] = _encode_digits(self._meter("cashable_ticket_exp"), 2)
        payload[9:11] = _encode_digits(self._meter("restricted_ticket_exp"), 2)
        return self._frame(0x7B, bytes(payload), total_len=15)

    def _reply_current_datetime(self) -> bytes:
        """0x7E: local time as BCD MMDDYYYYHHMMSS. The only thing in here that isn't made up."""
        now_digits = time.strftime("%m%d%Y%H%M%S", time.localtime())
        payload = bytes(int(now_digits[i : i + 2], 16) for i in range(0, 14, 2))
        return self._frame(0x7E, payload, total_len=11)

    def _reply_legacy_bonus_meters(self, req: bytes) -> bytes:
        """0x9A: legacy bonus meters for game N: deductible, non-deductible, wager match."""
        game_number = _decode_digits(req[1:3]) if len(req) >= 3 else 0
        payload = bytearray(14)
        payload[0] = 0x00
        payload[1] = game_number & 0xFF
        payload[2:6] = _encode_digits(self._meter("legacy_deductible"), 4)
        payload[6:10] = _encode_digits(self._meter("legacy_non_deductible"), 4)
        payload[10:14] = _encode_digits(self._meter("legacy_wager_match"), 4)
        return self._frame(0x9A, bytes(payload), total_len=18)

    def _reply_enabled_features(self, req: bytes) -> bytes:
        """0xA0: enabled feature bytes for game N, taken from meters features_1..3."""
        payload = bytearray(8)
        if len(req) >= 3:
            payload[0:2] = req[1:3]
        else:
            payload[0:2] = _encode_digits(max(1, self._meter("selected_game")), 2)
        payload[2] = self._meter("features_1") & 0xFF
        payload[3] = self._meter("features_2") & 0xFF
        payload[4] = self._meter("features_3") & 0xFF
        return self._frame(0xA0, bytes(payload), total_len=12)

    def _asset_number_bytes(self) -> bytes:
        """The asset number as 4 bytes of little endian binary. Not BCD, for once.

        Comes from the asset_number meter, or 123456789 (15 CD 5B 07 on the wire) if you never set
        one. The readers build it the same way: asset 1 goes out as 01 00 00 00.
        """
        asset = self._meter("asset_number") or DEFAULT_ASSET_NUMBER
        return (asset & 0xFFFFFFFF).to_bytes(4, "little")
