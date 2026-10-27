import time

from morpheus_vlt.core.chaos import ChaosProfile


def test_chaos_disabled_returns_payload() -> None:
    profile = ChaosProfile(enabled=False)
    assert profile.apply(b"abc") == [b"abc"]


def test_chaos_drop_returns_empty() -> None:
    profile = ChaosProfile(enabled=True, drop_rate=1.0, seed=1)
    assert profile.apply(b"abc") == []


def test_chaos_corrupt_changes_payload() -> None:
    profile = ChaosProfile(enabled=True, corrupt_rate=1.0, seed=2)
    out = profile.apply(b"\x10\x20\x30")
    assert out[0] != b"\x10\x20\x30"


def test_chaos_flip_bit_changes_payload() -> None:
    profile = ChaosProfile(enabled=True, flip_bit_rate=1.0, seed=3)
    out = profile.apply(b"\x10\x20\x30")
    assert out[0] != b"\x10\x20\x30"


def test_chaos_duplicate_returns_two_payloads() -> None:
    profile = ChaosProfile(enabled=True, duplicate_rate=1.0, seed=4)
    out = profile.apply(b"abc")
    assert out == [b"abc", b"abc"]


def test_chaos_delay_calls_sleep(monkeypatch) -> None:
    called = {"slept": False}

    def _sleep(_seconds: float) -> None:
        called["slept"] = True

    monkeypatch.setattr(time, "sleep", _sleep)
    profile = ChaosProfile(enabled=True, delay_ms_min=1, delay_ms_max=1, seed=5)
    profile.apply(b"abc")
    assert called["slept"] is True
