"""R. Franco simulator. Plain ASCII lines, a password prompt, and Spanish. Lots of Spanish."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.state import MachineState


# (label printed on the line, meter it reads). The labels have dots where the legacy reader regex
# has wildcards. Don't "fix" them into real words, the regex is the boss here.
TOTALS_LAYOUT: tuple[tuple[str, str], ...] = (
    ("total...e", "play"),
    ("total...s", "win"),
    ("total...pa", "plays"),
)


# Same deal for REGISTROS: bets, coins and bills in/out by denomination, and the in_h_* bills.
REGISTROS_LAYOUT: tuple[tuple[str, str], ...] = (
    ("partid.a.1", "bet_1"),
    ("partid.a.2", "bet_2"),
    ("partid.a.3", "bet_3"),
    ("mo.e.10c", "in_10c"),
    ("mo.s.10c", "out_10c"),
    ("mo.e.20c", "in_20c"),
    ("mo.s.20c", "out_20c"),
    ("mo.e.50c", "in_50c"),
    ("mo.s.50c", "out_50c"),
    ("mo.e.1e", "in_1e"),
    ("mo.s.1e", "out_1e"),
    ("mo.e.2e", "in_2e"),
    ("mo.s.2e", "out_2e"),
    ("bille.5e", "in_5e"),
    ("bills.5e", "out_5e"),
    ("bille.10e", "in_10e"),
    ("bills.10e", "out_10e"),
    ("bille.20e", "in_20e"),
    ("bills.20e", "out_20e"),
    ("bille.50e", "in_50e"),
    ("bills.50e", "out_50e"),
    ("bilho.5e", "in_h_5e"),
    ("bilho.10e", "in_h_10e"),
    ("bilho.20e", "in_h_20e"),
    ("bilho.50e", "in_h_50e"),
)


# The 7 ESTADO bits when nobody set meters rfranco_status_1..7 in the state.
DEFAULT_STATUS_BITS: tuple[int, ...] = (1, 1, 0, 0, 0, 0, 0)


@dataclass
class RFrancoSimulator:
    """ASCII line-oriented R. Franco simulator for the legacy reader flow.

    Commands, one per line, case doesn't matter:
      C          -> "CLAVE:" then the next line is the key ("RF" unless you change it)
      ESTADO     -> "ESTADO=" plus 7 status bits
      TOTALES    -> play, win and plays totals
      REGISTROS  -> the detailed registers, only after the key, plus both door counters
    Anything else gets "ERR COMANDO". Each command gets echoed back first unless `echo_commands`
    is off. Lines end in CR, LF or CRLF, and they can arrive in as many pieces as TCP feels like.
    """

    name: str = "rfranco"
    state: MachineState = field(default_factory=MachineState)

    key: str = "RF"
    require_key: bool = True
    echo_commands: bool = True

    _rx: bytearray = field(default_factory=bytearray, init=False, repr=False)
    _awaiting_key: bool = field(default=False, init=False, repr=False)
    _authenticated: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.require_key:
            self._authenticated = True

    @property
    def authenticated(self) -> bool:
        """True once the right key went through. Wrong key flips it back to False."""
        return self._authenticated

    def handle(self, data: bytes) -> bytes:
        """Buffer `data`, answer every complete line, keep the leftovers for next time."""
        if not data:
            return b""

        self._rx.extend(data)
        out = bytearray()

        while True:
            line = self._pop_line()
            if line is None:
                break

            line = line.strip()
            if not line:
                continue

            if self.echo_commands:
                out.extend(line)
                out.extend(b"\r\n")
            out.extend(self._dispatch_line(line))

        return bytes(out)

    def _dispatch_line(self, line: bytes) -> bytes:
        """Answer one line. The reply carries its own CRLF."""
        text = line.decode("utf-8", errors="ignore").strip()
        if not text:
            return b""

        if self._awaiting_key:
            # Some readers send C twice before the key. Prompt again instead of treating "C"
            # as a wrong password. Patience is cheaper than a support call.
            if text.upper() == "C":
                return b"CLAVE:\r\n"
            self._awaiting_key = False
            if not self.require_key or text.upper() == self.key.upper():
                self._authenticated = True
                return b"OK\r\n"
            self._authenticated = False
            return b"ERR CLAVE\r\n"

        command = text.upper()
        if command == "C":
            self._awaiting_key = True
            return b"CLAVE:\r\n"
        if command == "ESTADO":
            return self._build_estado()
        if command == "TOTALES":
            return self._build_totales()
        if command == "REGISTROS":
            return self._build_registros()
        return b"ERR COMANDO\r\n"

    def _build_estado(self) -> bytes:
        """ESTADO=xxxxxxx, one bit per status. Override any of them with meter rfranco_status_N."""
        bits: list[str] = []
        for idx, default in enumerate(DEFAULT_STATUS_BITS, start=1):
            name = f"rfranco_status_{idx}"
            value = int(self.state.meters.get(name, default))
            bits.append("1" if value else "0")
        return f"ESTADO={''.join(bits)}\r\n".encode("ascii")

    def _build_totales(self) -> bytes:
        """One "label  value" line per TOTALS_LAYOUT entry. The parser splits on the spaces."""
        lines = [f"{label}  {self._get_meter(name)}" for label, name in TOTALS_LAYOUT]
        return ("\r\n".join(lines) + "\r\n").encode("ascii")

    def _build_registros(self) -> bytes:
        """The detailed registers plus door counters. No key, no registers."""
        if self.require_key and not self._authenticated:
            return b"ERR CLAVE\r\n"

        lines = [f"{label}  {self._get_meter(name)}" for label, name in REGISTROS_LAYOUT]
        lines.append(f"Puerta  {self._get_meter('doorsup_c')}")
        lines.append(f"PuertaInf  {self._get_meter('doorinf_c')}")
        return ("\r\n".join(lines) + "\r\n").encode("ascii")

    def _get_meter(self, name: str) -> int:
        return int(self.state.get_meter(name))

    def _pop_line(self) -> bytes | None:
        """Pull one line off the buffer, or None if there's no complete line yet.

        Takes CR, LF, CRLF or LFCR as the line ending. Everybody picked a different one in 1985
        and we are all still paying for it.
        """
        if not self._rx:
            return None

        pos: int | None = None
        terminator: int | None = None
        for idx, value in enumerate(self._rx):
            if value in (0x0A, 0x0D):
                pos = idx
                terminator = value
                break

        if pos is None or terminator is None:
            return None

        line = bytes(self._rx[:pos])
        del self._rx[: pos + 1]

        # Eat the other half of a two-byte line ending so it doesn't count as an empty line.
        if self._rx:
            if terminator == 0x0D and self._rx[0] == 0x0A:
                del self._rx[0]
            elif terminator == 0x0A and self._rx[0] == 0x0D:
                del self._rx[0]

        return line
