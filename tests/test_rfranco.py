import re

from morpheus_vlt.protocols.rfranco import REGISTROS_LAYOUT, RFrancoSimulator

REX_TOT = rb"^total\.[\.e,\.s,pa]"
REX_REG = rb"^(mo\.[e,s]|bil[le,ls,ho]|partid\.a\.[1,2,3])"


def _parse_values(payload: bytes, pattern: bytes) -> list[int]:
    rows = filter(lambda row: re.match(pattern, row, re.IGNORECASE), payload.split(b"\r\n"))
    return [int(re.split(rb" +", row)[1]) for row in rows]


def test_rfranco_key_exchange_sets_authenticated() -> None:
    sim = RFrancoSimulator()

    resp = sim.handle(b"C\r\nRF\r\n")

    assert b"CLAVE" in resp.upper()
    assert b"OK" in resp.upper()
    assert sim.authenticated is True


def test_rfranco_key_exchange_accepts_c_plus_key_fallback() -> None:
    sim = RFrancoSimulator()

    sim.handle(b"C\r\n")
    resp = sim.handle(b"C\r\nRF\r\n")

    assert b"CLAVE" in resp.upper()
    assert b"OK" in resp.upper()
    assert sim.authenticated is True


def test_rfranco_totales_and_registros_match_reader_regex() -> None:
    sim = RFrancoSimulator()
    sim.state.set_meter("play", 1001)
    sim.state.set_meter("win", 222)
    sim.state.set_meter("plays", 77)

    for idx, (_label, meter) in enumerate(REGISTROS_LAYOUT, start=1):
        sim.state.set_meter(meter, idx * 10)

    sim.handle(b"C\r\nRF\r\n")
    totals = sim.handle(b"TOTALES\r\n")
    registros = sim.handle(b"REGISTROS\r\n")

    assert _parse_values(totals, REX_TOT) == [1001, 222, 77]
    assert _parse_values(registros, REX_REG) == [
        int(sim.state.get_meter(meter)) for _label, meter in REGISTROS_LAYOUT
    ]


def test_rfranco_registros_requires_key() -> None:
    sim = RFrancoSimulator()

    resp = sim.handle(b"REGISTROS\r\n")

    assert b"ERR CLAVE" in resp.upper()


def test_rfranco_handles_chunked_lines() -> None:
    sim = RFrancoSimulator(require_key=False, echo_commands=False)

    assert sim.handle(b"EST") == b""

    resp = sim.handle(b"ADO\r\n")
    bits = [chr(b) for b in resp if chr(b) in {"0", "1"}]

    assert b"ESTADO=" in resp
    assert len(bits) >= 7
