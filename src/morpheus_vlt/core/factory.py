"""Turns a protocol name into a ready-to-lie simulator."""

from __future__ import annotations

from typing import Any

from ..models.state import MachineState
from ..protocols.dex import DexSimulator
from ..protocols.rfranco import RFrancoSimulator
from ..protocols.sas import SASSimulator
from ..protocols.unidesa import UnidesaSimulator
from ..protocols.vdai import VDAISimulator


def build_protocol(
    name: str,
    state: MachineState,
    protocol_type: str | None,
    addr: int,
    dex_file: str | None = None,
    dex_comm_id: str | None = None,
    dex_revision: str | None = None,
    dex_response_code: str | None = None,
) -> Any:
    """Build the simulator for `name` and hand it the shared `state`.

    `protocol_type` only matters to VDAI, `addr` only to SAS, and the `dex_*` knobs only to DEX.
    Everybody else ignores what they don't need, like a sane coworker. An unknown name exits the
    program instead of guessing, because guessing is how you end up debugging at 2 AM.
    """
    if name in ("unidesa", "cirsa"):
        sim = UnidesaSimulator(name=name)
        sim.state = state
        return sim
    if name == "sas":
        sim = SASSimulator()
        sim.state = state
        sim.addr = addr
        return sim
    if name == "vdai":
        sim = VDAISimulator()
        sim.state = state
        if protocol_type:
            sim.protocol_type = protocol_type
        return sim
    if name == "rfranco":
        sim = RFrancoSimulator()
        sim.state = state
        return sim
    if name == "dex":
        sim = DexSimulator()
        sim.state = state
        sim.configure_identity(
            communication_id=dex_comm_id,
            revision_level=dex_revision,
            response_code=dex_response_code,
        )
        if dex_file:
            sim.load_evadts_file(dex_file)
        return sim
    raise SystemExit(f"Unknown protocol: {name}")
