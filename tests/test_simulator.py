from morpheus_vlt.core.chaos import ChaosProfile
from morpheus_vlt.core.framing import UnidesaMessage, build_unidesa_reply
from morpheus_vlt.core.simulator import Simulator, build_handler
from morpheus_vlt.protocols.unidesa import UnidesaSimulator


class _DummyProtocol:
    name = "dummy"

    def handle(self, data: bytes) -> bytes:
        return data[::-1]


def test_simulator_without_chaos() -> None:
    sim = Simulator(protocol=_DummyProtocol())
    assert sim.handle(b"abc") == b"cba"


def test_simulator_with_chaos_duplicate() -> None:
    chaos = ChaosProfile(enabled=True, duplicate_rate=1.0, seed=1)
    sim = Simulator(protocol=_DummyProtocol(), chaos=chaos)
    assert sim.handle(b"abc") == b"cbacba"


def _unidesa_frame(cmd: int, nm: int = 0x01) -> bytes:
    return build_unidesa_reply(sd=0x00, so=0x00, nm=nm, cmd=cmd, data=b"")


def test_unidesa_handler_answers_every_frame_in_a_glued_read() -> None:
    handler = build_handler(Simulator(protocol=UnidesaSimulator()), "unidesa")

    out = handler(_unidesa_frame(0x0B, nm=1) + _unidesa_frame(0x06, nm=2))

    first = UnidesaMessage.parse(out)
    second = UnidesaMessage.parse(out[8 + first.nd :])
    assert (first.nm, first.cmd) == (1, 0x0B)
    assert (second.nm, second.cmd) == (2, 0x06)


def test_unidesa_handler_waits_for_the_rest_of_a_split_frame() -> None:
    handler = build_handler(Simulator(protocol=UnidesaSimulator()), "cirsa")
    frame = _unidesa_frame(0x0B)

    assert handler(frame[:3]) == b""
    assert UnidesaMessage.parse(handler(frame[3:])).cmd == 0x0B


def test_unidesa_handler_skips_a_bad_frame_and_keeps_going(caplog) -> None:
    handler = build_handler(Simulator(protocol=UnidesaSimulator()), "unidesa")
    bad = bytearray(_unidesa_frame(0x0B))
    bad[-2] ^= 0xFF  # wreck the checksum

    out = handler(bytes(bad) + _unidesa_frame(0x06))

    assert UnidesaMessage.parse(out).cmd == 0x06
    assert "checksum mismatch" in caplog.text


def test_unidesa_handler_ignores_idle_ticks() -> None:
    handler = build_handler(Simulator(protocol=UnidesaSimulator()), "unidesa")

    assert handler(b"") == b""


def test_other_protocols_get_silence_instead_of_an_exception(caplog) -> None:
    class _Exploding:
        name = "boom"

        def handle(self, data: bytes) -> bytes:
            raise RuntimeError("kaboom")

    handler = build_handler(Simulator(protocol=_Exploding()), "sas")

    assert handler(b"\x01") == b""
    assert "kaboom" in caplog.text
