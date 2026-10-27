import pytest

from morpheus_vlt.core.framing import UnidesaMessage, build_unidesa_reply, xor55_checksum


def test_xor55_checksum() -> None:
    assert xor55_checksum(b"\x01\x02\x03") == ((1 + 2 + 3) ^ 0x55) & 0xFF


def test_build_unidesa_reply_roundtrip() -> None:
    payload = b"\x10\x20"
    raw = build_unidesa_reply(sd=0xFF, so=0x00, nm=0x01, cmd=0x16, data=payload)
    msg = UnidesaMessage.parse(raw)
    msg.validate()

    assert msg.sd == 0xFF
    assert msg.so == 0x00
    assert msg.nm == 0x01
    assert msg.cmd == 0x16
    assert msg.data == payload


def test_unidesa_parse_too_short() -> None:
    with pytest.raises(ValueError, match="frame too short"):
        UnidesaMessage.parse(b"\x02\x00")


def test_unidesa_validate_bad_stx_ext() -> None:
    msg = UnidesaMessage(
        stx=0x00,
        sd=0x01,
        so=0x00,
        nm=0x01,
        cmd=0x16,
        nd=0,
        data=b"",
        chk=0x00,
        ext=0x00,
    )
    with pytest.raises(ValueError, match="bad STX/EXT"):
        msg.validate()


def test_unidesa_validate_checksum_mismatch() -> None:
    msg = UnidesaMessage(
        stx=0x02,
        sd=0x01,
        so=0x00,
        nm=0x01,
        cmd=0x16,
        nd=0,
        data=b"",
        chk=0x00,
        ext=0x03,
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        msg.validate()
