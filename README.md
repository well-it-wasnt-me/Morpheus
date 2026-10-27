# Morpheus

Morpheus is the Greek god best known for sleep, but he had a side gig: mimicking people.

He's the god of dreams and the son of Hypnos (Sleep), and he can take any human form perfectly: the
voice, the walk, the mannerisms, the mood. The whole act.

This package does the same thing for slot machines. Less divine, more bytes.

# What this is

`morpheus-vlt` is a small Python package that pretends to be a VLT. Your reader scripts connect to it,
ask for meters, and get back replies shaped exactly like the real machines. They never find out.

Why bother? Because the real machine weighs 90 kg, lives in a bar three towns over, and the owner
wants it back by Friday. This way you test parsing and error handling at your desk, and with the chaos
options you can make it fail on purpose instead of waiting for production to do it at 3 AM.

## What it fakes (so far)

- **Unidesa/Cirsa**: binary frames with the XOR55 checksum, counter paging and custom counter selection.
  `cirsa` is the same simulator under a different name tag.
- **SAS**: replies sized and laid out the way the readers slice them, BCD meters, saspy-compatible CRC.
  The 9-bit electrical layer is not emulated (see the bottom of this page for why).
- **VDAI**: the "stats printout" style ASCII dump, in three flavors.
- **RFranco**: ASCII command/reply (`C`, `ESTADO`, `TOTALES`, `REGISTROS`) with the key prompt.
- **DEX/UCS**: both handshakes plus the EVA-DTS file transfer (DLE STX ... DLE ETB/ETX + CRC16).

Plus **chaos**: drop, duplicate, corrupt, flip bits and delay replies, to find out what your client
does when life gets real.

## Documentation

The full docs live at **https://well-it-wasnt-me.github.io/Morpheus/**: guides, byte-level protocol pages,
architecture, API reference, and a list of known issues so you don't have to discover them yourself. This
README is the short version.

## Install (editable)

From the repo root:

```bash
python -m pip install -e .
```

That gets you the `morpheus-vlt` command and the pytest plugin.

## Developer quickstart

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -e .
pytest --cov=src/morpheus_vlt --cov-report=term-missing
```

The full contributor guide is in `docs/development.md`. It's short. I made sure. To preview the docs site
locally:

```bash
python -m pip install -r requirements-docs.txt
mkdocs serve
```

## The protocols, up close

* **Unidesa / Cirsa binary framed protocol**
    * Frame: `STX SD SO NM CMD ND DATA CHK EXT`
    * Checksum: `(sum(bytes) ^ 0x55) & 0xFF`. That's the whole algorithm. Don't overthink it.
    * Commands: access (`0x0B`), logout (`0x06`), custom selection (`0x2E`), read counters (`0x16`).
      Anything else gets error `0x01`.
    * Counter reply payload: `group | first | received | (id | value[4 LE]) * received`, capped at 32
      counters per page.
    * Group `0xFF` reads the custom selection. Any other group reads the default counter list.
    * In the CLI, a bad checksum gets no reply at all. The error is logged, the frame is skipped, and
      the client gets to sit in silence and think about what it did.

* **SAS (shape of the bytes, not the electrons)**
    * The readers send with 9-bit addressing and CRC16, then slice the reply at fixed offsets and
      lengths without checking anything. So the simulator's job is getting the sizes right. The CRC
      is right too, saspy agrees with it.
    * Requests can start with an `0x80` or `0x82` "nine-bit" marker byte and the address, or just the
      address. All of those work.
    * General poll: 1 byte, `0x00` ("nothing happened").
    * Ack-only commands (shutdown, startup, sound, bill acceptor enable/disable, maintenance mode and
      friends): 1 byte, the machine's address.
    * `0x0F` select meters: 28 bytes.
    * `0x2F` custom meters: 57 bytes, parsed as 10 blocks of 5 bytes. Always the same 10 meters,
      whatever the request asked for.
    * Single meter polls (most of `0x10` to `0x4A`), multi-meter polls (`0x18`, `0x19`, `0x1C`, `0x1E`),
      machine info (`0x1F`, `0x21`, `0x51` to `0x56`), tickets and validation (`0x3D`, `0x48`, `0x4C`,
      `0x4D`, `0x50`, `0x57`, `0x58`, `0x70`, `0x71`, `0x7B`), date/time (`0x7E`) and a few more.
    * AFT (`0x72`, `0x73`, `0x74`): transfers actually move the `credits` meter, so a test can push
      money in and watch it land. Then take it out. The machine always wins, even the fake one.
    * Anything unknown: `0xFF` then zeros, padded to the length the reader expects.
    * On a PTY it announces its address byte while the line is idle, until the host says something.

* **VDAI "stats printout"**
    * Returns newline-delimited ASCII laid out exactly the way the reader's parser reads it. Pick the
      flavor with `--vdai-type`: `m` generic, `a` anniversario, `b` bally.
    * The layouts are rebuilt from the reader's parsing code, not copied from a real printout. Nobody
      had one. The tests run the reader's own regexes against them.
    * One stats page per request line, whatever the request says. Like a support hotline. Silence gets
      silence, so it doesn't spam a quiet PTY.

* **RFranco ASCII command set**
    * `C` prompts `CLAVE:`, the next line is the key (`RF`). Wrong key gets `ERR CLAVE`.
    * `ESTADO` returns 7 status bits, `TOTALES` the play/win/plays totals, `REGISTROS` the detailed
      registers (key required, no key no registers).
    * Every command gets echoed back first, and the lines match the legacy parser regexes.
    * Lines can end in CR, LF or CRLF and arrive in as many pieces as they like.

* **DEX/UCS**
    * Both handshakes, then the EVA-DTS file in `DLE STX ... DLE ETB/ETX` blocks with CRC16.
    * NAK gets the same block again. After the last block: EOT, and it's ready for the next reader.
    * No `--dex-file`? You get a tiny built-in EVA-DTS file that's just legit enough to parse.

## Run a simulator

```bash
# Unidesa/Cirsa
morpheus-vlt --protocol unidesa --port 9000

# SAS (address 0x01 by default)
morpheus-vlt --protocol sas --port 9001 --sas-addr 0x01

# VDAI (generic)
morpheus-vlt --protocol vdai --port 9002 --vdai-type m

# DEX/UCS
morpheus-vlt --protocol dex --port 9003 --dex-file ./evadts.txt

# RFranco
morpheus-vlt --protocol rfranco --port 9004
```

Everything defaults to `127.0.0.1:9000`. `--help` lists the rest. It runs until you hit Ctrl+C.

## Fake serial port (PTY)

The readers talk serial. A PTY is a serial port that isn't there, and pyserial can't tell the
difference. Linux and macOS only. Windows users get TCP and my sympathy.

```bash
# Creates /tmp/ttyMODEM -> /dev/pts/<n>
morpheus-vlt --protocol unidesa --transport pty --tty-name ttyMODEM

# Or put the symlink anywhere you like (under /dev you'll need permissions)
morpheus-vlt --protocol sas --transport pty --tty-path /dev/ttyWHATEVER
```

Point your client at the symlink. Skip both flags and you get a bare `/dev/pts/<n>` that changes every
run. It's printed in the log, and good luck remembering it.

### Example: SAS over a PTY

1. Start the SAS simulator with a stable name:
```bash
morpheus-vlt --protocol sas --transport pty --tty-name ttySAS --sas-addr 0x01
```

2. Send `0x0F` (select meters) and read the reply:
```python
import serial

ser = serial.Serial("/tmp/ttySAS", baudrate=9600, timeout=1)
ser.write(bytes([0x82, 0x01, 0x0F]))  # optional 0x82 "nine-bit" marker, address, command
resp = ser.read(28)  # select meters reply is 28 bytes. Not 27. Not 29.
print(resp.hex())
ser.close()
```

## Pytest integration

Once installed, the package registers a pytest plugin. No conftest, no import. You get a
`morpheus_vlt_server` fixture that starts a simulator in a background thread and stops it at teardown.

```python
def test_reader(morpheus_vlt_server):
    sim = morpheus_vlt_server(protocol="unidesa", transport="pty", tty_name="ttyMODEM")
    # sim.endpoint is the device path for a PTY, or "host:port" for TCP
```

Keyword arguments, all optional: `protocol` (default `unidesa`), `transport` (`tcp` or `pty`), `host`,
`port` (0 picks a free one), `tty_name`, `tty_path`, `vdai_type`, `sas_addr`, `chaos` (a
`ChaosProfile`) and `state` (a `MachineState`). You get back a handle with `transport`, `endpoint` and
`stop()`. Without `tty_path`, PTY symlinks land in a pytest temp dir, so they don't litter `/tmp`.

The fixture returns once the server is listening, so connect right away. It handles requests the same
way the CLI does: Unidesa frames get cut out of the byte stream, and a protocol error gets logged instead
of killing the server. The one catch: DEX always gets the built-in EVA-DTS file.

## Starting state

Create a JSON file:

```json
{
  "meters": {
    "play": 123456,
    "win": 120000,
    "plays": 999
  },
  "counters": {
    "1": 123456,
    "2": 120000,
    "17": 999
  }
}
```

Then:

```bash
morpheus-vlt --protocol unidesa --state ./state.json
```

Counter ids are strings in the file because JSON says so. They turn back into numbers on load. Anything
you don't set reads as 0. Which protocol reads what:

- **Unidesa/Cirsa**: `counters`, by id. The default id list is `DEFAULT_SELECTED_COUNTER_IDS` in
  `unidesa.py`.
- **SAS**: `meters`. `play`, `win`, `plays`, `coin_in`, `coin_out`, `drop`, `jackpot`, `credits`,
  `bill_*` and a lot more. `SINGLE_METER_COMMANDS` and the `_reply_*` methods in `sas.py` have the
  whole zoo. Many polls take a list of names and use the first one you set, so `play` can stand in for
  `coin_in`.
- **VDAI**: `meters`. `plays`, `play`, `win`, `coin_in`, `coin_out`, `bill_in`, `bill_out`, plus
  denomination counts like `in_10c` and `out_50e` for anniversario and bally. Money is in cents and gets
  printed in euros. Bally works out the totals from the counts, so set the counts.
- **RFranco**: `meters`. `play`, `win`, `plays`, the names in `REGISTROS_LAYOUT`, `doorsup_c`,
  `doorinf_c`, and `rfranco_status_1` to `rfranco_status_7` for the ESTADO bits.
- **DEX/UCS**: nothing. It sends the EVA-DTS file and that's that.

## Chaos testing

* drop replies (simulate timeouts)
* duplicate replies
* corrupt a byte (simulate checksum/CRC failures)
* flip a random bit
* add random latency

Because chaos is love.

```bash
# 10% timeouts, 5% corrupted replies, 50-250 ms added latency
morpheus-vlt --protocol unidesa --chaos \
  --drop-rate 0.10 --corrupt-rate 0.05 \
  --delay-ms-min 50 --delay-ms-max 250
```

The rates do nothing without `--chaos`. That one will get you at least once. It got me.

The order things happen in: drop, corrupt, flip, delay, duplicate. A duplicate is a copy of the
already-mangled reply, so if it's wrong it's consistently wrong. Want the same disaster on every run?
Set `MORPHEUS_VLT_CHAOS_SEED`. It seeds Python's global `random`, so anything else in the process using
`random` gets reproducible too, whether it wanted to or not.

## What's intentionally not faked (yet)

- SAS electrical-layer parity and the 9th bit. You can't meaningfully emulate them over raw TCP bytes
  or a PTY. The simulator gets by on reply sizes and offsets, and so do the readers.
- Per-game SAS meters. Ask for game 1 or game 40, you get the same machine-wide meters.
- The serial PTY endpoint used to be on this list. I didn't shove it in by default because it's
  OS-specific and I don't love suffering as much as I used to. Then I added it anyway. Turns out I do.
