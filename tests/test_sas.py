from morpheus_vlt.protocols.sas import (
    CMD_CUSTOM_METERS,
    CMD_DISABLE_BILL,
    CMD_ENABLE_BILL,
    CMD_EVENT_POLL,
    CMD_SELECT_METERS,
    SASSimulator,
    _sas_crc,
)


def _encode_digits(value: int, length: int) -> bytes:
    digits = f"{int(value):0{length * 2}d}"[-(length * 2) :]
    return bytes(int(digits[i : i + 2], 16) for i in range(0, len(digits), 2))


def _assert_valid_crc(frame: bytes) -> None:
    assert frame[-2:] == bytes(_sas_crc(frame[:-2]))


def test_empty_data_announces_address_until_activity() -> None:
    sim = SASSimulator(idle_announce_interval=0.0)
    assert sim.handle(b"") == bytes([sim.addr])
    assert sim.handle(b"") == bytes([sim.addr])
    assert sim.handle(bytes([0x82, sim.addr])) == b""
    assert sim.handle(b"") == b""


def test_select_meters_reply_shape() -> None:
    sim = SASSimulator()
    sim.state.set_meter("play", 1000)
    sim.state.set_meter("win", 2000)

    resp = sim.handle(bytes([0x82, sim.addr, CMD_SELECT_METERS]))
    assert len(resp) == 28
    assert resp[0] == sim.addr
    assert resp[1] == CMD_SELECT_METERS
    _assert_valid_crc(resp)

    data = resp[1:-2]
    play = int(data[5:9].hex())
    win = int(data[9:13].hex())
    assert play == 1000
    assert win == 2000


def test_custom_meters_reply_shape() -> None:
    sim = SASSimulator()
    sim.state.set_meter("play", 111)
    sim.state.set_meter("win", 222)
    sim.state.set_meter("plays", 333)

    resp = sim.handle(bytes([sim.addr, CMD_CUSTOM_METERS]))
    assert len(resp) == 57
    assert resp[:5] == bytes([sim.addr, CMD_CUSTOM_METERS, 0x34, 0x00, 0x00])
    _assert_valid_crc(resp)

    blocks = resp[5:-2]
    first_code = blocks[0]
    first_val = int(blocks[1:5].hex())
    assert first_code == 0
    assert first_val == 111


def test_enable_disable_bill_ack() -> None:
    sim = SASSimulator()
    for cmd in (CMD_ENABLE_BILL, CMD_DISABLE_BILL):
        resp = sim.handle(bytes([sim.addr, cmd]))
        assert resp == bytes([sim.addr])


def test_event_poll_reply() -> None:
    sim = SASSimulator()
    resp = sim.handle(bytes([sim.addr, (CMD_EVENT_POLL + sim.addr) & 0xFF]))
    assert resp == b"\x00"


def test_unknown_command_reply() -> None:
    sim = SASSimulator()
    resp = sim.handle(bytes([sim.addr, 0xDE]))
    assert len(resp) == 8
    assert resp[0] == sim.addr
    assert resp[1] == 0xDE
    assert resp[2] == 0xFF
    _assert_valid_crc(resp)


def test_version_and_machine_id_responses() -> None:
    sim = SASSimulator()

    ver = sim.handle(bytes([sim.addr, 0x54, 0x00]))
    assert len(ver) == 20
    _assert_valid_crc(ver)
    ver_data = ver[1:-2]
    assert int(ver_data[2:5].hex()) == 603

    mid = sim.handle(bytes([sim.addr, 0x1F]))
    assert len(mid) == 24
    _assert_valid_crc(mid)
    mid_data = mid[1:-2]
    assert mid_data[6] == 0x01


def test_aft_transfer_updates_credits_and_transaction_id() -> None:
    sim = SASSimulator()
    tx = bytes.fromhex("20202020202020202020202020202021")

    aft_in_cmd = bytearray([0x72, 0x44, 0x00, 0x00, 0x00])
    aft_in_cmd.extend(_encode_digits(1500, 5))
    aft_in_cmd.extend(_encode_digits(0, 5))
    aft_in_cmd.extend(_encode_digits(0, 5))
    aft_in_cmd.append(0x00)
    aft_in_cmd.extend(bytes.fromhex("15CD5B07"))
    aft_in_cmd.extend(b"\x00" * 20)
    aft_in_cmd.append(len(tx))
    aft_in_cmd.extend(tx)
    aft_in_cmd.extend(b"\x00" * 8)

    aft_in_resp = sim.handle(bytes([0x82, sim.addr]) + bytes(aft_in_cmd) + b"\x00\x00")
    assert len(aft_in_resp) == 82
    _assert_valid_crc(aft_in_resp)

    aft_data = aft_in_resp[1:-2]
    assert int(aft_data[6:11].hex()) == 1500
    assert aft_data[26] == len(tx)
    assert aft_data[27 : 27 + len(tx)] == tx
    assert sim.state.get_meter("credits") == 1500

    poll_resp = sim.handle(bytes([0x82, sim.addr, 0x72, 0x02, 0xFF, 0x00, 0x00, 0x00]))
    assert len(poll_resp) == 82
    _assert_valid_crc(poll_resp)
    poll_data = poll_resp[1:-2]
    assert poll_data[26] == len(tx)
    assert poll_data[27 : 27 + len(tx)] == tx


def test_pdf_command_shapes() -> None:
    sim = SASSimulator()
    expected_lengths = {
        0x1B: 24,
        0x21: 6,
        0x3D: 13,
        0x48: 10,
        0x4C: 11,
        0x4D: 35,
        0x4F: 11,
        0x50: 14,
        0x53: 26,
        0x56: 8,
        0x57: 10,
        0x58: 5,
        0x70: 20,
        0x71: 20,
        0x7B: 15,
        0xA0: 12,
    }

    for cmd, expected_len in expected_lengths.items():
        req = bytes([sim.addr, cmd])
        if cmd in (0x50,):
            req = bytes([sim.addr, cmd, 0x00])
        if cmd in (0x53, 0xA0):
            req = bytes([sim.addr, cmd, 0x00, 0x01])
        resp = sim.handle(req)
        assert len(resp) == expected_len
        assert resp[0] == sim.addr
        assert resp[1] == cmd
        _assert_valid_crc(resp)


def test_saspy_command_coverage() -> None:
    sim = SASSimulator()
    saspy_commands = {
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
        0x0F,
        0x10,
        0x11,
        0x12,
        0x13,
        0x14,
        0x15,
        0x16,
        0x17,
        0x18,
        0x19,
        0x1A,
        0x1B,
        0x1C,
        0x1E,
        0x1F,
        0x20,
        0x21,
        0x2A,
        0x2B,
        0x2C,
        0x2D,
        0x2E,
        0x31,
        0x32,
        0x33,
        0x34,
        0x35,
        0x36,
        0x37,
        0x38,
        0x39,
        0x3A,
        0x3B,
        0x3C,
        0x3D,
        0x3E,
        0x3F,
        0x40,
        0x41,
        0x42,
        0x43,
        0x44,
        0x45,
        0x46,
        0x47,
        0x48,
        0x49,
        0x4A,
        0x4C,
        0x4D,
        0x4F,
        0x50,
        0x51,
        0x52,
        0x53,
        0x54,
        0x55,
        0x56,
        0x57,
        0x58,
        0x6E,
        0x70,
        0x71,
        0x72,
        0x73,
        0x74,
        0x7B,
        0x7E,
        0x7F,
        0x8A,
        0x94,
        0x9A,
        0xA0,
        0xAA,
    }

    ack_only = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0E, 0x2E, 0x7F, 0x8A, 0x94, 0xAA}

    for cmd in sorted(saspy_commands):
        req = bytes([sim.addr, cmd])
        if cmd in (0x50,):
            req = bytes([sim.addr, cmd, 0x00])
        if cmd in (0x52, 0x53, 0x9A, 0xA0):
            req = bytes([sim.addr, cmd, 0x00, 0x01])
        resp = sim.handle(req)
        assert resp != b""
        if cmd in ack_only:
            assert resp == bytes([sim.addr])
        else:
            assert resp[0] == sim.addr
            assert resp[1] == cmd
            _assert_valid_crc(resp)


def _aft_request(transfer_type: int, cashable: int, transfer_code: int = 0x00) -> bytes:
    # Same field order the jupiter-os reader uses: code, index, type, three amounts, flags, asset, key, tx id.
    tx = bytes(17)
    cmd = bytearray([0x72, 0x44, transfer_code, 0x00, transfer_type])
    cmd.extend(_encode_digits(cashable, 5))
    cmd.extend(_encode_digits(0, 5))
    cmd.extend(_encode_digits(0, 5))
    cmd.append(0x00)
    cmd.extend(bytes.fromhex("01000000"))
    cmd.extend(b"\x00" * 20)
    cmd.append(len(tx))
    cmd.extend(tx)
    cmd.extend(b"\x00" * 7)
    return bytes(cmd)


def test_aft_out_takes_credits_away() -> None:
    sim = SASSimulator()
    sim.state.set_meter("credits", 5000)

    resp = sim.handle(bytes([sim.addr]) + _aft_request(0x80, 1500))

    assert sim.state.get_meter("credits") == 3500
    data = resp[1:-2]
    assert data[5] == 0x80  # transfer type echoed where the reader looks for it
    assert int(data[6:11].hex()) == 1500


def test_aft_out_floors_credits_at_zero() -> None:
    sim = SASSimulator()
    sim.state.set_meter("credits", 100)

    sim.handle(bytes([sim.addr]) + _aft_request(0x80, 1500))

    assert sim.state.get_meter("credits") == 0


def test_aft_cancel_moves_nothing() -> None:
    sim = SASSimulator()
    sim.state.set_meter("credits", 5000)

    sim.handle(bytes([sim.addr]) + _aft_request(0x00, 1500, transfer_code=0x80))

    assert sim.state.get_meter("credits") == 5000


def test_aft_status_poll_reports_the_last_transfer() -> None:
    sim = SASSimulator()
    sim.handle(bytes([sim.addr]) + _aft_request(0x00, 2500))

    # The exact poll jupiter-os sends after a transfer, CRC and all.
    res = sim.handle(bytes([sim.addr]) + bytes.fromhex("7202ff000f22"))

    assert int(res[7:12].hex()) == 2500  # where aft_trx_id reads the amount
    assert res[6] == 0x00
    assert sim.state.get_meter("credits") == 2500


def test_aft_status_poll_before_any_transfer_reports_zero() -> None:
    sim = SASSimulator()

    resp = sim.handle(bytes([sim.addr]) + bytes.fromhex("7202ff00"))

    assert int(resp[1:-2][6:11].hex()) == 0
    assert sim.state.get_meter("credits") == 0


def test_games_since_power_up_and_door_closure() -> None:
    sim = SASSimulator()
    sim.state.set_meter("games_last_power_up", 1234)
    sim.state.set_meter("games_since_door_closure", 56)

    resp = sim.handle(bytes([sim.addr, 0x18]))

    assert len(resp) == 8
    assert resp[2:4] == bytes.fromhex("1234")
    assert resp[4:6] == bytes.fromhex("0056")
    _assert_valid_crc(resp)


def test_asset_number_is_little_endian_binary() -> None:
    sim = SASSimulator()
    sim.state.set_meter("asset_number", 1)

    resp = sim.handle(bytes([sim.addr, 0x74, 0x00]))

    assert resp[1:-2][2:6] == bytes.fromhex("01000000")  # what the reader sends for asset 1


def test_default_asset_number_is_123456789() -> None:
    sim = SASSimulator()

    resp = sim.handle(bytes([sim.addr, 0x74, 0x00]))

    assert int.from_bytes(resp[1:-2][2:6], "little") == 123456789
