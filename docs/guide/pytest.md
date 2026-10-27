# Pytest plugin

Installing the package registers a pytest plugin through the `pytest11` entry point. No conftest, no imports.
It just shows up in every test session, like a cold. You get one fixture: `morpheus_vlt_server`.

## The fixture

`morpheus_vlt_server` is a factory. Call it to start a simulator in a background thread. Call it again for
another one. Every server it started gets stopped at teardown, so you don't have to remember.

```python
def test_reader_reads_meters(morpheus_vlt_server):
    sim = morpheus_vlt_server(protocol="sas", transport="pty")
    # sim.endpoint is a device path. Hand it to the reader.
```

It returns once the server is actually listening, so you can connect right away. If the server doesn't come up
within 5 seconds, you get a `RuntimeError` instead of a mystery.

### Arguments

All keyword-only, all optional.

| Argument    | Default       | What it does                                                         |
|-------------|---------------|----------------------------------------------------------------------|
| `protocol`  | `"unidesa"`   | `unidesa`, `cirsa`, `sas`, `vdai`, `dex` or `rfranco`                 |
| `transport` | `"tcp"`       | `tcp` or `pty`                                                       |
| `host`      | `"127.0.0.1"` | TCP bind address                                                     |
| `port`      | `0`           | TCP port. `0` picks a free one                                       |
| `tty_name`  | `ttyMORPHEUS` | PTY symlink name, created inside a pytest temp dir                   |
| `tty_path`  | none          | Full PTY symlink path. Beats `tty_name`                              |
| `vdai_type` | `"m"`         | VDAI flavor                                                          |
| `sas_addr`  | `0x01`        | SAS machine address                                                  |
| `chaos`     | none          | A `ChaosProfile`. See [chaos testing](chaos.md)                      |
| `state`     | empty         | A `MachineState`. See [machine state](state.md)                      |

DEX always gets the built-in EVA-DTS file here. There's no knob for it. Yet.

### What you get back

A `SimHandle` with three things:

- `transport`: `"tcp"` or `"pty"`.
- `endpoint`: `"host:port"` for TCP, the symlink path for a PTY.
- `stop()`: shuts the server down early, if a test wants to see what the reader does when the machine dies.

## Examples

### TCP

```python
import socket

from morpheus_vlt.core.framing import UnidesaMessage, build_unidesa_reply


def test_unidesa_access(morpheus_vlt_server):
    sim = morpheus_vlt_server(protocol="unidesa")
    host, port = sim.endpoint.split(":")

    with socket.create_connection((host, int(port)), timeout=2) as conn:
        conn.sendall(build_unidesa_reply(sd=0x00, so=0x00, nm=0x01, cmd=0x0B, data=b""))
        reply = UnidesaMessage.parse(conn.recv(4096))

    assert reply.data == b"\x00"
```

### Serial (PTY)

```python
import serial


def test_sas_select_meters(morpheus_vlt_server):
    sim = morpheus_vlt_server(protocol="sas", transport="pty")

    with serial.Serial(sim.endpoint, baudrate=9600, timeout=1) as ser:
        ser.write(bytes([0x82, 0x01, 0x0F]))
        assert len(ser.read(28)) == 28
```

### With numbers

```python
from morpheus_vlt.models.state import MachineState


def test_reader_sees_the_meters(morpheus_vlt_server):
    state = MachineState()
    state.set_meter("play", 123456)
    state.set_meter("win", 120000)
    sim = morpheus_vlt_server(protocol="rfranco", transport="pty", state=state)

    ...  # run the reader against sim.endpoint, check it stored 123456 and 120000

    state.set_meter("play", 123500)  # the simulator keeps a reference, so the next reply has the new value
```

### On a bad day

```python
from morpheus_vlt.core.chaos import ChaosProfile


def test_reader_retries(morpheus_vlt_server):
    chaos = ChaosProfile(enabled=True, drop_rate=0.3, seed=42)
    sim = morpheus_vlt_server(protocol="sas", transport="pty", chaos=chaos)
    ...
```

## How requests get handled

The fixture uses the same request handler as the CLI:

- Unidesa/Cirsa frames get cut out of the byte stream, so frames glued together or split across reads all get
  answered.
- If the protocol raises, the error gets logged and the reply is empty. The server keeps going. A test sees the
  same silence a reader would, and the traceback lands in the captured log.

## Without installing

From a bare checkout the entry point isn't registered, so load the plugin yourself. In `conftest.py`:

```python
pytest_plugins = ["morpheus_vlt.pytest_plugin"]
```

Don't do that in a project that also has the package installed. Pytest will load the plugin twice and refuse
to start. This repo's own `tests/conftest.py` checks first and only loads it when nobody else did.

## Skip the sockets

For protocol logic, you don't need the fixture at all. Call `handle()` with bytes and check the bytes that come
back. Fast, no threads, no flakes:

```python
from morpheus_vlt.protocols.rfranco import RFrancoSimulator


def test_estado():
    assert RFrancoSimulator(echo_commands=False).handle(b"ESTADO\r\n") == b"ESTADO=1100000\r\n"
```
