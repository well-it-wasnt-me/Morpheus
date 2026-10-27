"""The `morpheus-vlt` command.

Parses flags, builds a protocol simulator, wraps it in chaos if asked nicely, then parks it on a TCP
port or a PTY until somebody hits Ctrl+C. That's the whole job. It's a doorman with argparse.
"""

from __future__ import annotations

import argparse
import json
import logging
import os

from ..core.chaos import ChaosProfile
from ..core.factory import build_protocol
from ..core.simulator import Simulator, build_handler
from ..core.transport import PtyByteServer, PtyConfig, ServerConfig, TCPByteServer
from ..models.state import MachineState


def _load_state(path: str | None) -> MachineState:
    """Load meters and counters from a JSON file, or start from zero if there isn't one.

    Counter ids come in as JSON keys, which means strings, because JSON says so. They get turned
    back into ints here so nobody else has to care.
    """
    if not path:
        return MachineState()
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    st = MachineState()
    for k, v in obj.get("meters", {}).items():
        st.set_meter(k, int(v))
    for k, v in obj.get("counters", {}).items():
        st.set_counter(int(k), int(v))
    return st


def main() -> None:
    """Run the simulator until somebody hits Ctrl+C or the laptop dies, whichever comes first."""
    p = argparse.ArgumentParser(
        prog="morpheus-vlt",
        description="VLT protocol simulator. Lies to your reader scripts so the machine doesn't.",
    )
    p.add_argument(
        "--protocol",
        required=True,
        choices=["unidesa", "cirsa", "sas", "vdai", "dex", "rfranco"],
        help="Protocol to fake. 'cirsa' is 'unidesa' wearing a different hat",
    )
    p.add_argument(
        "--transport", choices=["tcp", "pty"], default="tcp", help="TCP socket or fake serial port"
    )
    p.add_argument("--host", default="127.0.0.1", help="TCP bind address")
    p.add_argument("--port", type=int, default=9000, help="TCP port")
    p.add_argument("--tty-name", help="Create a PTY symlink with this name inside --tty-dir")
    p.add_argument("--tty-dir", default="/tmp", help="Where --tty-name lands. Default /tmp")
    p.add_argument("--tty-path", help="Full PTY symlink path. Beats --tty-name and --tty-dir")
    p.add_argument("--state", help="JSON file with the starting meters/counters")
    p.add_argument(
        "--vdai-type",
        choices=["m", "a", "b"],
        help="VDAI flavor: m generic, a anniversario, b bally",
    )
    p.add_argument(
        "--sas-addr",
        type=lambda x: int(x, 0),
        default=0x01,
        help="SAS machine address. Hex works (0x01). Default 0x01",
    )
    p.add_argument("--dex-file", help="EVADTS file to hand over. Default: a tiny built-in one")
    p.add_argument("--dex-comm-id", help="DEX communication ID (10 chars)")
    p.add_argument("--dex-rev", help="DEX revision level (6 chars, e.g. R01L01)")
    p.add_argument("--dex-response-code", help="DEX response code (2 chars)")

    # Chaos knobs. None of the rates do a thing unless --chaos is on. Ask me how I know.
    p.add_argument("--chaos", action="store_true", help="Turn on fault injection")
    p.add_argument("--drop-rate", type=float, default=0.0, help="Chance (0-1) a reply never shows")
    p.add_argument("--duplicate-rate", type=float, default=0.0, help="Chance (0-1) it shows twice")
    p.add_argument("--corrupt-rate", type=float, default=0.0, help="Chance (0-1) a byte is mangled")
    p.add_argument("--flip-bit-rate", type=float, default=0.0, help="Chance (0-1) a bit is flipped")
    p.add_argument("--delay-ms-min", type=int, default=0, help="Minimum added latency in ms")
    p.add_argument("--delay-ms-max", type=int, default=0, help="Maximum added latency in ms")

    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level))

    state = _load_state(args.state)
    protocol = build_protocol(
        args.protocol,
        state,
        args.vdai_type,
        args.sas_addr,
        dex_file=args.dex_file,
        dex_comm_id=args.dex_comm_id,
        dex_revision=args.dex_rev,
        dex_response_code=args.dex_response_code,
    )

    chaos = ChaosProfile(
        enabled=args.chaos,
        drop_rate=args.drop_rate,
        duplicate_rate=args.duplicate_rate,
        corrupt_rate=args.corrupt_rate,
        flip_bit_rate=args.flip_bit_rate,
        delay_ms_min=args.delay_ms_min,
        delay_ms_max=args.delay_ms_max,
    )

    sim = Simulator(protocol=protocol, chaos=chaos)
    # Frame splitting for Unidesa, error swallowing for everybody. Same handler the fixture uses.
    handler = build_handler(sim, args.protocol)

    if args.transport == "pty":
        link_path = args.tty_path
        if not link_path and args.tty_name:
            link_path = os.path.join(args.tty_dir, args.tty_name)
        srv = PtyByteServer(PtyConfig(link_path=link_path), handler)
        logging.getLogger("morpheus-vlt").info("Listening on PTY %s (%s)", link_path or "auto", args.protocol)
    else:
        srv = TCPByteServer(ServerConfig(host=args.host, port=args.port), handler)
        logging.getLogger("morpheus-vlt").info("Listening on %s:%d (%s)", args.host, args.port, args.protocol)

    try:
        srv.start()
    except KeyboardInterrupt:
        logging.getLogger("morpheus-vlt").info("Interrupted. Stopping server, going home")
    finally:
        srv.stop()


if __name__ == "__main__":
    main()
