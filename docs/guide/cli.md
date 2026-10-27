# Command line

```text
morpheus-vlt --protocol {unidesa,cirsa,sas,vdai,dex,rfranco} [options]
```

One process, one fake machine, one protocol. Want two machines? Run it twice on two ports. It's not
proud.

## Picking a protocol

| Flag | Default | What it does |
| --- | --- | --- |
| `--protocol` | (required) | `unidesa`, `cirsa`, `sas`, `vdai`, `dex` or `rfranco` |
| `--state` | none | JSON file with the starting meters and counters. See [machine state](state.md). |

`cirsa` is `unidesa` wearing a different hat. Same simulator, different name tag.

## Transport

| Flag          | Default     | What it does                                                               |
|---------------|-------------|----------------------------------------------------------------------------|
| `--transport` | `tcp`       | `tcp` for a socket, `pty` for a [fake serial port](serial.md).             |
| `--host`      | `127.0.0.1` | TCP bind address. Use `0.0.0.0` if the reader lives on another box.        |
| `--port`      | `9000`      | TCP port. Every protocol defaults to 9000, so pick different ones if you run several. |
| `--tty-name`  | none        | PTY only. Create a symlink with this name inside `--tty-dir`.              |
| `--tty-dir`   | `/tmp`      | PTY only. Where `--tty-name` lands.                                        |
| `--tty-path`  | none        | PTY only. Full symlink path. Beats `--tty-name` and `--tty-dir`.           |

## Protocol knobs

| Flag                  | Protocol | Default        | What it does                                                   |
|-----------------------|----------|----------------|----------------------------------------------------------------|
| `--sas-addr`          | SAS      | `0x01`         | Machine address. Decimal or hex (`0x01`), `int(x, 0)` rules.   |
| `--vdai-type`         | VDAI     | `m`            | Printout flavor: `m` generic, `a` anniversario, `b` bally.     |
| `--dex-file`          | DEX      | built-in file  | EVA-DTS file to hand over.                                     |
| `--dex-comm-id`       | DEX      | `0000000001`   | Communication ID. Padded with zeros on the left to 10 chars.   |
| `--dex-rev`           | DEX      | `R01L01`       | Revision level. Padded with spaces on the right to 6 chars.    |
| `--dex-response-code` | DEX      | `00`           | Response code in the second handshake. 2 chars.                |

Flags for a protocol you didn't pick are ignored. Quietly. Like advice.

## Chaos

| Flag               | Default | What it does                                                   |
|--------------------|---------|----------------------------------------------------------------|
| `--chaos`          | off     | Turns fault injection on. Without it, the rates below do nothing. |
| `--drop-rate`      | `0.0`   | Chance (0 to 1) a reply never shows up.                        |
| `--duplicate-rate` | `0.0`   | Chance a reply shows up twice.                                 |
| `--corrupt-rate`   | `0.0`   | Chance one byte of the reply gets mangled.                     |
| `--flip-bit-rate`  | `0.0`   | Chance one bit of the reply gets flipped.                      |
| `--delay-ms-min`   | `0`     | Minimum added latency, in milliseconds.                        |
| `--delay-ms-max`   | `0`     | Maximum added latency, in milliseconds.                        |

The [chaos testing](chaos.md) guide has the order of operations and the reproducibility trick.

## Logging

| Flag          | Default | What it does                                   |
|---------------|---------|------------------------------------------------|
| `--log-level` | `INFO`  | `DEBUG`, `INFO`, `WARNING` or `ERROR`.         |

## Examples

```bash
# Unidesa on the default port
morpheus-vlt --protocol unidesa

# SAS at address 0x05, reachable from the rest of the network
morpheus-vlt --protocol sas --host 0.0.0.0 --port 9001 --sas-addr 0x05

# VDAI, Bally flavor, with numbers
morpheus-vlt --protocol vdai --port 9002 --vdai-type b --state ./state.json

# DEX with a real EVA-DTS dump and a custom identity
morpheus-vlt --protocol dex --port 9003 --dex-file ./evadts.txt --dex-comm-id 1234567890 --dex-rev R02L01

# RFranco on a fake serial port at /tmp/ttyRF
morpheus-vlt --protocol rfranco --transport pty --tty-name ttyRF

# Unidesa on a bad day
morpheus-vlt --protocol unidesa --chaos --drop-rate 0.1 --corrupt-rate 0.05 --delay-ms-min 50 --delay-ms-max 250
```

## What happens when things go wrong

- **Unidesa/Cirsa**: the CLI buffers the byte stream and cuts it into whole frames, because TCP doesn't care
  where your frames end. A frame with a bad checksum or bad delimiters gets logged and skipped. No reply. The
  client gets to sit in silence and think about what it did.
- **Everybody else**: each chunk of bytes goes straight to the protocol. If the protocol raises, the error gets
  logged and the reply is empty. Silence again, which is honestly what real hardware does.
- **Ctrl+C**: logs `Interrupted. Stopping server, going home`, closes the socket or PTY, removes the symlink.
