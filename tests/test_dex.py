from morpheus_vlt.protocols.dex import (
    ACK0,
    ACK1,
    DLE_ETB,
    DLE_ETX,
    DLE_SOH,
    DLE_STX,
    ENQ,
    EOT,
    ETX,
    MAX_HANDSHAKE_BYTES,
    NAK,
    DexSimulator,
    dex_crc16_bytes,
)


def _op_request(comm_id: bytes, rev: bytes, op: bytes = b"R") -> bytes:
    payload = comm_id + op + rev
    crc = dex_crc16_bytes(payload + bytes([ETX]))
    return DLE_SOH + payload + DLE_ETX + crc.to_bytes(2, "little")


def _parse_handshake(resp: bytes) -> bytes:
    assert resp.startswith(DLE_SOH)
    end = resp.find(DLE_ETX)
    assert end != -1
    payload = resp[len(DLE_SOH):end]
    crc = int.from_bytes(resp[end + len(DLE_ETX): end + len(DLE_ETX) + 2], "little")
    assert dex_crc16_bytes(payload + bytes([ETX])) == crc
    return payload


def test_dex_handshake_and_transfer() -> None:
    sim = DexSimulator()
    sim.load_evadts_lines(["LINE1", "LINE2"])

    comm_id = sim.communication_id
    rev = sim.revision_level

    assert sim.handle(ENQ) == ACK0
    assert sim.handle(_op_request(comm_id, rev)) == ACK1
    assert sim.handle(EOT) == ENQ

    resp = sim.handle(ACK0)
    payload = _parse_handshake(resp)
    assert payload.startswith(sim.response_code)

    assert sim.handle(ACK1) == EOT + ENQ

    resp = sim.handle(ACK0)
    assert resp.startswith(DLE_STX)
    assert DLE_ETB in resp  # not the last block, so ETB. More to come

    resp = sim.handle(ACK1)
    assert resp.startswith(DLE_STX)
    assert DLE_ETX in resp  # last block, so ETX. Show is over

    assert sim.handle(ACK0) == EOT


def test_dex_bad_crc_nak() -> None:
    sim = DexSimulator()
    comm_id = sim.communication_id
    rev = sim.revision_level

    assert sim.handle(ENQ) == ACK0
    bad_msg = DLE_SOH + comm_id + b"R" + rev + DLE_ETX + b"\x00\x00"
    assert sim.handle(bad_msg) == NAK

    assert sim.handle(_op_request(comm_id, rev)) == ACK1


def test_dex_handshake_request_split_across_reads() -> None:
    sim = DexSimulator()
    request = _op_request(sim.communication_id, sim.revision_level)

    assert sim.handle(ENQ) == ACK0
    assert sim.handle(request[:8]) == b""
    assert sim.handle(request[8:]) == ACK1


def test_dex_whole_session_one_byte_at_a_time() -> None:
    sim = DexSimulator()
    sim.load_evadts_lines(["LINE1", "LINE2"])

    def feed(data: bytes) -> bytes:
        return b"".join(sim.handle(bytes([b])) for b in data)

    assert feed(ENQ) == ACK0
    assert feed(_op_request(sim.communication_id, sim.revision_level)) == ACK1
    assert feed(EOT) == ENQ
    assert feed(ACK0).startswith(DLE_SOH)
    assert feed(ACK1) == EOT + ENQ
    assert DLE_ETB in feed(ACK0)
    assert DLE_ETX in feed(ACK1)
    assert feed(ACK0) == EOT


def test_dex_unterminated_handshake_gets_dropped_and_resyncs() -> None:
    sim = DexSimulator()
    assert sim.handle(ENQ) == ACK0

    assert sim.handle(DLE_SOH + b"A" * (MAX_HANDSHAKE_BYTES + 10)) == b""

    assert sim.handle(_op_request(sim.communication_id, sim.revision_level)) == ACK1
