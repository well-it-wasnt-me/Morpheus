"""VDAI simulator. The machine prints its stats like a receipt, the reader regexes the receipt.

Nobody had a real printout lying around, so these layouts are rebuilt backwards from the reader's
own parsing code (oblivion's `lib/protocol/vdai.py`): which lines its regex keeps, how it pulls the
numbers out of them, and which positions it reads. The labels are made up. The positions, the
number formats and the line shapes are exactly what the reader needs, and the tests run the
reader's own expressions against them to keep it that way.

Money meters are in cents and get printed in euros. Counts get printed as counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.state import MachineState

# Meters that hold money (cents). Everything else is a count.
MONEY_METERS = {"coin_in", "bill_in", "tot_in", "coin_out", "bill_out", "tot_out", "play", "win"}

# Denomination suffix -> (value in cents, a name without digits in it). The anniversario regex
# fishes numbers out of the whole line, labels included, so a label like "10c" becomes data.
DENOMINATIONS = {
    "10c": (10, "TEN CENT"),
    "20c": (20, "TWENTY CENT"),
    "50c": (50, "FIFTY CENT"),
    "1e": (100, "ONE EURO"),
    "2e": (200, "TWO EURO"),
    "5e": (500, "FIVE EURO"),
    "10e": (1000, "TEN EURO"),
    "20e": (2000, "TWENTY EURO"),
    "50e": (5000, "FIFTY EURO"),
}

# Generic ("m"): 16 values. With 13 or more, the reader takes coin_in, bill_in, tot_in,
# coin_out, bill_out, tot_out from positions 0, 1, 4, 5, 6, 10, then plays, play, win from 12,
# 13, 14. None marks a position it never reads, which prints as 0.00.
GENERIC_LAYOUT: tuple[str | None, ...] = (
    "coin_in", "bill_in", None, None, "tot_in", "coin_out", "bill_out", None,
    None, None, "tot_out", None, "plays", "play", "win", None,
)

# Anniversario ("a"): 46 values. The reader takes the money totals from positions 6 to 11,
# plays/play/win from 43 to 45, and the denomination counters from 14 to 41, skipping 19.
ANNIVERSARIO_LAYOUT: tuple[str | None, ...] = (
    None, None, None, None, None, None,
    "coin_in", "bill_in", "tot_in", "coin_out", "bill_out", "tot_out",
    None, None,
    "in_s_10c", "in_s_20c", "in_s_50c", "in_s_1e", "in_s_2e",
    None,
    "in_s_5e", "in_s_10e", "in_s_20e", "in_s_50e",
    "in_10c", "in_20c", "in_50c", "in_1e", "in_2e", "in_5e", "in_10e", "in_20e", "in_50e",
    "out_10c", "out_20c", "out_50c", "out_1e", "out_2e", "out_5e", "out_10e", "out_20e", "out_50e",
    None,
    "plays", "play", "win",
)

# Bally ("b"): 45 values, zipped against the reader's reshuffled counter table. The reader
# deletes the 8 values right before the last 4, so those positions are filler. It computes
# coin_in, bill_in, coin_out and bill_out itself from the denomination counts.
BALLY_LAYOUT: tuple[str | None, ...] = (
    "in_h_2e", "in_h_1e", "in_h_20c", "in_h_10c", "in_h_50e", "in_h_20e", "in_h_10e", "in_h_5e",
    "in_s_2e", "in_s_1e", "in_s_50c", "in_s_20c", "in_s_10c", "in_s_50e", "in_s_20e", "in_s_10e",
    "in_s_5e",
    "plays", "play", "win",
    "in_50e", "in_20e", "in_10e", "in_5e", "in_2e", "in_1e", "in_50c", "in_20c", "in_10c",
    "out_2e", "out_1e", "out_20c", "out_10c",
    None, None, None, None, None, None, None, None,
    "out_50e", "out_20e", "out_10e", "out_5e",
)

# Bally lines that aren't denomination counts, and the label each one starts with.
BALLY_LABELS = {"plays": "TOTAL PARTIDAS", "play": "PUNTOS APOSTADOS", "win": "PUNTOS GANADOS"}

# A request is one line. Anything this long without a line feed is noise, not a request.
MAX_REQUEST_BYTES = 256


def _money(cents: int, sep: str) -> str:
    """Cents as euros with exactly two decimals, `sep` in between. Integer math, no floats."""
    cents = max(0, int(cents))
    return f"{cents // 100}{sep}{cents % 100:02d}"


def _denomination(name: str) -> tuple[int, str]:
    """Value in cents and spelled-out name for the denomination at the end of a meter name."""
    return DENOMINATIONS[name.rsplit("_", 1)[1]]


@dataclass
class VDAISimulator:
    """ASCII-style "printer" protocol simulator.

    The reader sends an ESC/P-ish "stats" request ending in a line feed, then reads whatever
    comes back until the line goes quiet and digs the numbers out with regexes, one set per
    machine family. Every complete request line gets one stats page. Partial requests wait for
    the rest. Silence gets silence, which matters on a PTY where the transport pokes the
    protocol with empty input every 100 ms.

    Meters used: coin_in, bill_in, coin_out, bill_out, plays, play and win for the generic and
    anniversario flavors, plus the in_*/in_s_*/in_h_*/out_* denomination counts for
    anniversario and bally. tot_in and tot_out are computed, not read.
    """

    name: str = "vdai"
    state: MachineState = field(default_factory=MachineState)

    protocol_type: str = "m"  # "m" generic, "a" anniversario, "b" bally

    _rx: bytearray = field(default_factory=bytearray, init=False, repr=False)

    def handle(self, data: bytes) -> bytes:
        """Return one stats page per complete request line. What the request says is not consulted."""
        if not data:
            return b""
        self._rx.extend(data)
        requests = self._rx.count(b"\n")
        if not requests:
            if len(self._rx) > MAX_REQUEST_BYTES:
                self._rx.clear()
            return b""
        del self._rx[: self._rx.rfind(b"\n") + 1]
        # Whatever it asked, the answer is the stats page. Like a support hotline.
        return self._page() * requests

    def _page(self) -> bytes:
        if self.protocol_type == "b":
            return self._reply_bally()
        if self.protocol_type == "a":
            return self._reply_anniversario()
        return self._reply_generic()

    def _value(self, name: str | None) -> int:
        """A meter by name, with tot_in/tot_out worked out from their parts. None reads as 0."""
        if name is None:
            return 0
        if name == "tot_in":
            return self.state.get_meter("coin_in") + self.state.get_meter("bill_in")
        if name == "tot_out":
            return self.state.get_meter("coin_out") + self.state.get_meter("bill_out")
        return self.state.get_meter(name)

    def _reply_generic(self) -> bytes:
        """Generic flavor: money on " < EU" lines, counts on lines that are only spaces and digits."""
        # The reader keeps lines matching '^( < EU| +\d+$)' and pulls '(\d+\.\d+|[^\.]\d+$)'
        # out of them. So money needs the " < EU" prefix and a decimal point, and a count needs
        # at least one space in front of it. The header doesn't match and gets ignored.
        lines = ["STATISTICS"]
        for name in GENERIC_LAYOUT:
            value = self._value(name)
            if name in MONEY_METERS or name is None:
                lines.append(f" < EU {_money(value, '.'):>12}")
            else:
                lines.append(f" {value:>11}")
        return ("\n".join(lines) + "\n").encode("ascii")

    def _reply_anniversario(self) -> bytes:
        """Anniversario flavor: one "LABEL: value" line per position, labels without digits."""
        # The reader keeps lines matching '(EU|.*: +[0-9]+\.*[0-9]+$)', which wants at least two
        # digits after the colon, so counts get zero padded. Money goes out as euros with two
        # decimals, and the reader drops the dot to get cents back. No floats involved, for once.
        lines = ["STATISTICS"]
        for name in ANNIVERSARIO_LAYOUT:
            value = self._value(name)
            if name is None:
                lines.append(f"SPARE: {value:02d}")
            elif name in MONEY_METERS:
                lines.append(f"{name.replace('_', ' ').upper()} EU: {_money(value, '.')}")
            elif name == "plays":
                lines.append(f"PLAYS: {value:02d}")
            else:
                direction, _, _ = name.partition("_")
                section = "IN S" if name.startswith("in_s_") else direction.upper()
                lines.append(f"{section} {_denomination(name)[1]}: {value:02d}")
        return ("\n".join(lines) + "\n").encode("ascii")

    def _reply_bally(self) -> bytes:
        """Bally flavor: labeled lines for plays/play/win, "count,00 = money" lines for the rest."""
        # The reader keeps lines matching '^(TOTAL PARTIDAS|PUNTOS| +\d+,\d+ =)' and pulls
        # '(\d+[,.]\d+|[^,.]\d+)' out of them. A line with exactly two hits gets divided, anything
        # else gets its first hit. A count line has four hits (count, 00, euros, cents), so the
        # reader takes the count and never touches the division. Leading spaces are not optional.
        lines = ["CONTADORES"]
        for name in BALLY_LAYOUT:
            value = self._value(name)
            if name in BALLY_LABELS:
                lines.append(f"{BALLY_LABELS[name]} {value:>11}")
                continue
            cents = value * _denomination(name)[0] if name else 0
            lines.append(f" {value:>9},00 = {_money(cents, ','):>12}")
        return ("\n".join(lines) + "\n").encode("ascii")
