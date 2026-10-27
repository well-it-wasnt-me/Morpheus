# Getting started

## Requirements

- Python 3.10 or newer.
- Linux or macOS if you want the fake serial port. Windows gets TCP and my sympathy.
- `pyserial`, which gets installed for you.

## Install

From a clone of the repo:

```bash
python -m pip install -e .
```

Or straight from GitHub, if you have access to the repo:

```bash
python -m pip install "git+https://github.com/well-it-wasnt-me/Morpheus.git"
```

Either way you get two things: the `morpheus-vlt` command, and a pytest plugin that shows up in every test
session on its own.

Check that it's alive:

```bash
morpheus-vlt --help
```

## Run your first fake machine

Start a Unidesa simulator on TCP port 9000:

```bash
morpheus-vlt --protocol unidesa --port 9000
```

```text
INFO:morpheus-vlt:Listening on 127.0.0.1:9000 (unidesa)
```

It sits there until you hit Ctrl+C. That's the whole user interface. I didn't bother with a GUI, and neither
did the slot machine.

## Talk to it

In another terminal, ask it for counters. Unidesa frames are binary and checksummed, so let the package build
them for you. `build_unidesa_reply` builds any frame, request or reply. The name is a little optimistic.

```python
import socket

from morpheus_vlt.core.framing import UnidesaMessage, build_unidesa_reply

# Read counters from the custom group (0xFF), starting at offset 0, through the end (last = 0).
request = build_unidesa_reply(sd=0x00, so=0x00, nm=0x01, cmd=0x16, data=bytes([0xFF, 0x00, 0x00]))

with socket.create_connection(("127.0.0.1", 9000), timeout=2) as conn:
    conn.sendall(request)
    reply = UnidesaMessage.parse(conn.recv(4096))
    reply.validate()

group, first, received = reply.data[0], reply.data[1], reply.data[2]
print(f"group={group:#04x} first={first} received={received}")
```

Every counter is 0, because nobody told it otherwise. A fresh machine and an honest one.

## Give it some numbers

Put the starting state in a JSON file:

```json
{
  "meters": {"play": 123456, "win": 120000, "plays": 999},
  "counters": {"1": 123456, "2": 120000, "17": 999}
}
```

```bash
morpheus-vlt --protocol unidesa --port 9000 --state ./state.json
```

Unidesa reads `counters`. Every other protocol reads `meters`. [Machine state](guide/state.md) has the list of
which names each protocol actually looks at.

## Use it from a test

```python
def test_reader_talks_to_fake_machine(morpheus_vlt_server):
    sim = morpheus_vlt_server(protocol="rfranco", transport="pty")
    # sim.endpoint is the PTY path. Hand it to your reader and let it do its thing.
```

No conftest, no imports. The [pytest plugin](guide/pytest.md) page covers the details and the two gotchas.

## Where next

- [Command line](guide/cli.md): every flag, what it does, and what it defaults to.
- [Fake serial ports](guide/serial.md): when your reader insists on `/dev/ttySomething`.
- [Chaos testing](guide/chaos.md): break things on purpose, on a schedule.
- [Protocols](protocols/index.md): byte by byte, for when the reader and the simulator disagree.
