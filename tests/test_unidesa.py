from morpheus_vlt.core.framing import UnidesaMessage, xor55_checksum
from morpheus_vlt.protocols.unidesa import (
    CMD_ACCESS,
    CMD_COUNTERS,
    CMD_CUSTOM_SELECT,
    CMD_LOGOUT,
    DEFAULT_SELECTED_COUNTER_IDS,
    GROUP_CUSTOM,
    GROUP_ZERO,
    UnidesaSimulator,
)


def _build_request(cmd: int, data: bytes = b"", nm: int = 0x01, sd: int = 0x00, so: int = 0x00) -> bytes:
    stx = 0x02
    ext = 0x03
    nd = len(data)
    hdr = bytes([stx, sd, so, nm, cmd, nd])
    chk = xor55_checksum(hdr + data)
    return hdr + data + bytes([chk, ext])


def _parse_response(resp: bytes) -> UnidesaMessage:
    msg = UnidesaMessage.parse(resp)
    msg.validate()
    return msg


def test_access_and_logout() -> None:
    sim = UnidesaSimulator()
    for cmd in (CMD_ACCESS, CMD_LOGOUT):
        resp = sim.handle(_build_request(cmd))
        msg = _parse_response(resp)
        assert msg.cmd == cmd
        assert msg.data == b"\x00"


def test_custom_select_updates_selection() -> None:
    sim = UnidesaSimulator()
    req = _build_request(CMD_CUSTOM_SELECT, bytes([0x00, 0x09, 0x00, 0x0A]))
    resp = sim.handle(req)
    msg = _parse_response(resp)
    assert msg.data == b"\x00"
    assert sim.selected_counters == [0x09, 0x0A]


def test_counters_custom_group_payload() -> None:
    sim = UnidesaSimulator()
    sim.selected_counters = [5, 6]
    sim.state.set_counter(5, 10)
    sim.state.set_counter(6, 20)

    req = _build_request(CMD_COUNTERS, bytes([GROUP_CUSTOM, 0x00, 0x01]))
    resp = sim.handle(req)
    msg = _parse_response(resp)

    assert msg.data[0] == GROUP_CUSTOM
    assert msg.data[1] == 0x00
    assert msg.data[2] == 2

    cid1 = msg.data[3]
    val1 = int.from_bytes(msg.data[4:8], "little")
    cid2 = msg.data[8]
    val2 = int.from_bytes(msg.data[9:13], "little")

    assert cid1 == 5
    assert val1 == 10
    assert cid2 == 6
    assert val2 == 20


def test_counters_group_zero_slicing() -> None:
    sim = UnidesaSimulator()
    target_id = DEFAULT_SELECTED_COUNTER_IDS[1]
    sim.state.set_counter(target_id, 1234)

    req = _build_request(CMD_COUNTERS, bytes([GROUP_ZERO, 0x01, 0x01]))
    resp = sim.handle(req)
    msg = _parse_response(resp)

    assert msg.data[2] == 1
    assert msg.data[3] == target_id
    assert int.from_bytes(msg.data[4:8], "little") == 1234


def test_counters_short_payload_error() -> None:
    sim = UnidesaSimulator()
    req = _build_request(CMD_COUNTERS, b"\x00\x01")
    resp = sim.handle(req)
    msg = _parse_response(resp)
    assert msg.data == b"\x01"


def test_unknown_cmd_returns_error() -> None:
    sim = UnidesaSimulator()
    req = _build_request(0x99, b"")
    resp = sim.handle(req)
    msg = _parse_response(resp)
    assert msg.data == b"\x01"
