import os
import select
import socket
import time

from morpheus_vlt.core.chaos import ChaosProfile
from morpheus_vlt.core.framing import UnidesaMessage, build_unidesa_reply
from morpheus_vlt.models.state import MachineState


def _read_pty(fd: int, timeout: float) -> bytes:
    deadline = time.time() + timeout
    got = b""
    while time.time() < deadline:
        if select.select([fd], [], [], 0.05)[0]:
            got += os.read(fd, 4096)
    return got


def test_tcp_server_is_ready_on_return(morpheus_vlt_server) -> None:
    sim = morpheus_vlt_server(protocol="unidesa")
    host, port = sim.endpoint.split(":")

    # No retry loop. If the fixture returned early, this is where it would blow up.
    with socket.create_connection((host, int(port)), timeout=2) as conn:
        conn.sendall(build_unidesa_reply(sd=0, so=0, nm=1, cmd=0x0B, data=b""))
        assert UnidesaMessage.parse(conn.recv(4096)).cmd == 0x0B


def test_tcp_unidesa_frames_glued_together_all_get_answers(morpheus_vlt_server) -> None:
    sim = morpheus_vlt_server(protocol="unidesa")
    host, port = sim.endpoint.split(":")
    frames = b"".join(build_unidesa_reply(sd=0, so=0, nm=n, cmd=0x0B, data=b"") for n in (1, 2, 3))

    with socket.create_connection((host, int(port)), timeout=2) as conn:
        conn.sendall(frames)
        out = b""
        while len(out) < 27:
            out += conn.recv(4096)

    assert [out[i + 3] for i in range(0, 27, 9)] == [1, 2, 3]


def test_pty_unidesa_survives_idle_ticks(morpheus_vlt_server) -> None:
    sim = morpheus_vlt_server(protocol="unidesa", transport="pty")
    time.sleep(0.3)  # a few idle ticks. Used to kill the server thread.

    fd = os.open(sim.endpoint, os.O_RDWR | os.O_NOCTTY)
    try:
        os.write(fd, build_unidesa_reply(sd=0, so=0, nm=1, cmd=0x0B, data=b""))
        assert UnidesaMessage.parse(_read_pty(fd, 0.5)).cmd == 0x0B
    finally:
        os.close(fd)


def test_pty_vdai_keeps_quiet_until_asked(morpheus_vlt_server) -> None:
    sim = morpheus_vlt_server(protocol="vdai", transport="pty")

    fd = os.open(sim.endpoint, os.O_RDWR | os.O_NOCTTY)
    try:
        assert _read_pty(fd, 0.4) == b""
        os.write(fd, b"\x05\x1bS12345678lGS  C  \n")
        assert _read_pty(fd, 0.4).count(b"STATISTICS") == 1
    finally:
        os.close(fd)


def test_state_gets_passed_through(morpheus_vlt_server) -> None:
    state = MachineState()
    state.set_meter("play", 1000)
    sim = morpheus_vlt_server(protocol="rfranco", state=state)
    host, port = sim.endpoint.split(":")

    with socket.create_connection((host, int(port)), timeout=2) as conn:
        conn.sendall(b"TOTALES\r\n")
        got = b""
        while b"total...pa" not in got:
            got += conn.recv(4096)

    assert b"total...e  1000" in got


def test_chaos_gets_passed_through(morpheus_vlt_server) -> None:
    chaos = ChaosProfile(enabled=True, drop_rate=1.0, seed=1)
    sim = morpheus_vlt_server(protocol="rfranco", chaos=chaos)
    host, port = sim.endpoint.split(":")

    with socket.create_connection((host, int(port)), timeout=0.5) as conn:
        conn.sendall(b"TOTALES\r\n")
        try:
            got = conn.recv(4096)
        except TimeoutError:
            got = b""

    assert got == b""  # every reply dropped, as ordered
