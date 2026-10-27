import json
from types import SimpleNamespace

import pytest

from morpheus_vlt.cli.main import _load_state, build_protocol
from morpheus_vlt.models.state import MachineState
from morpheus_vlt.protocols.dex import DexSimulator
from morpheus_vlt.protocols.rfranco import RFrancoSimulator
from morpheus_vlt.protocols.sas import SASSimulator
from morpheus_vlt.protocols.unidesa import UnidesaSimulator
from morpheus_vlt.protocols.vdai import VDAISimulator


def test_load_state(tmp_path) -> None:
    payload = {
        "meters": {"play": 123, "win": 456},
        "counters": {"1": 10, "2": 20},
    }
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    state = _load_state(str(path))
    assert isinstance(state, MachineState)
    assert state.get_meter("play") == 123
    assert state.get_meter("win") == 456
    assert state.get_counter(1) == 10
    assert state.get_counter(2) == 20


def test_build_protocol_unidesa() -> None:
    state = MachineState()
    sim = build_protocol("unidesa", state, None, addr=0x01)
    assert isinstance(sim, UnidesaSimulator)
    assert sim.state is state


def test_build_protocol_sas_sets_addr() -> None:
    state = MachineState()
    sim = build_protocol("sas", state, None, addr=0x02)
    assert isinstance(sim, SASSimulator)
    assert sim.state is state
    assert sim.addr == 0x02


def test_build_protocol_vdai_sets_type() -> None:
    state = MachineState()
    sim = build_protocol("vdai", state, "b", addr=0x01)
    assert isinstance(sim, VDAISimulator)
    assert sim.state is state
    assert sim.protocol_type == "b"


def test_build_protocol_dex_defaults(tmp_path) -> None:
    dex_path = tmp_path / "evadts.txt"
    dex_path.write_text("DXS*SIM*VA*V0/6*1\nDXE*1*1\n", encoding="utf-8")
    state = MachineState()
    sim = build_protocol("dex", state, None, addr=0x01, dex_file=str(dex_path))
    assert isinstance(sim, DexSimulator)
    assert sim.state is state


def test_build_protocol_rfranco() -> None:
    state = MachineState()
    sim = build_protocol("rfranco", state, None, addr=0x01)
    assert isinstance(sim, RFrancoSimulator)
    assert sim.state is state


def test_build_protocol_unknown_raises() -> None:
    state = MachineState()
    with pytest.raises(SystemExit, match="Unknown protocol"):
        build_protocol("nope", state, None, addr=0x01)


def test_main_calls_stop_on_keyboard_interrupt(monkeypatch) -> None:
    import morpheus_vlt.cli.main as cli_main

    class _DummyProtocol:
        name = "dummy"

        def handle(self, data: bytes) -> bytes:
            return data

    class _InterruptingServer:
        instance = None

        def __init__(self, *_args, **_kwargs) -> None:
            self.stopped = False
            _InterruptingServer.instance = self

        def start(self) -> None:
            raise KeyboardInterrupt

        def stop(self) -> None:
            self.stopped = True

    args = SimpleNamespace(
        protocol="rfranco",
        transport="tcp",
        host="127.0.0.1",
        port=0,
        tty_name=None,
        tty_dir="/tmp",
        tty_path=None,
        state=None,
        vdai_type=None,
        sas_addr=0x01,
        dex_file=None,
        dex_comm_id=None,
        dex_rev=None,
        dex_response_code=None,
        chaos=False,
        drop_rate=0.0,
        duplicate_rate=0.0,
        corrupt_rate=0.0,
        flip_bit_rate=0.0,
        delay_ms_min=0,
        delay_ms_max=0,
        log_level="INFO",
    )

    monkeypatch.setattr(cli_main.argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(cli_main, "build_protocol", lambda *_args, **_kwargs: _DummyProtocol())
    monkeypatch.setattr(cli_main, "TCPByteServer", _InterruptingServer)

    cli_main.main()

    assert _InterruptingServer.instance is not None
    assert _InterruptingServer.instance.stopped is True
