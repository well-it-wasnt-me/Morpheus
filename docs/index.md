# Morpheus

Morpheus is the Greek god best known for sleep, but he had a side gig: mimicking people.

He's the god of dreams and the son of Hypnos (Sleep), and he can take any human form perfectly: the voice,
the walk, the mannerisms, the mood. The whole act.

This package does the same thing for slot machines. Less divine, more bytes.

## What this is

`morpheus-vlt` is a small Python package that pretends to be a VLT, a video lottery terminal: a gambling
machine with a screen and a strong opinion about your money. Your reader scripts connect to it over TCP or
a fake serial port, ask for meters, and get back replies shaped exactly like the real machines. They never
find out.

Why bother? Because the real machine weighs 90 kg, lives in a bar three towns over, and the owner wants it
back by Friday. With Morpheus you test parsing and error handling at your desk, and with the chaos options
you can make it fail on purpose instead of waiting for production to do it at 3 AM.

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __Get going__

    ---

    Install it, run it, point a reader at it. Five minutes. Four if you skip the coffee, which I don't
    recommend.

    [:octicons-arrow-right-24: Getting started](getting-started.md)

-   :material-lan-connect:{ .lg .middle } __Protocols__

    ---

    Unidesa/Cirsa, SAS, VDAI, RFranco and DEX/UCS. Byte layouts, commands, and what's faked versus what's
    real.

    [:octicons-arrow-right-24: Protocols](protocols/index.md)

-   :material-fire:{ .lg .middle } __Chaos testing__

    ---

    Dropped replies, duplicates, corrupted bytes, flipped bits, latency. Everything a real serial line does
    to you, on demand.

    [:octicons-arrow-right-24: Chaos testing](guide/chaos.md)

-   :material-test-tube:{ .lg .middle } __Pytest plugin__

    ---

    A fixture that spins up a fake machine per test and cleans up after itself. Unlike some coworkers.

    [:octicons-arrow-right-24: Pytest plugin](guide/pytest.md)

</div>

## What it fakes (so far)

| Protocol        | Wire format                              | What the readers get out of it                     |
|-----------------|------------------------------------------|----------------------------------------------------|
| Unidesa / Cirsa | Binary frames, XOR55 checksum            | Counters by id, paged, with custom selection       |
| SAS             | Binary, BCD meters, CRC-16/KERMIT        | Meters, machine info, tickets, AFT transfers       |
| VDAI            | ASCII "stats printout"                   | A stats page the reader regexes numbers out of     |
| RFranco         | ASCII lines, CR/LF                       | Key prompt, status bits, totals, registers         |
| DEX / UCS       | DLE framed blocks, CRC-16/ARC            | An EVA-DTS audit file, one block at a time         |

Plus **chaos**: drop, duplicate, corrupt, flip bits and delay replies, to find out what your client does when
life gets real. Because chaos is love.

## Thirty-second tour

```bash
python -m pip install -e .
morpheus-vlt --protocol sas --transport pty --tty-name ttySAS
```

```python
import serial

ser = serial.Serial("/tmp/ttySAS", baudrate=9600, timeout=1)
ser.write(bytes([0x82, 0x01, 0x0F]))  # wake-up marker, address, "send meters 10 to 15"
print(ser.read(28).hex())             # 28 bytes. Not 27. Not 29.
```

Your reader script thinks it's talking to a slot machine. It's talking to a Python process. Nobody has to know.

## Where things are

- New here? [Getting started](getting-started.md), then the [command line](guide/cli.md) guide.
- Writing tests? The [pytest plugin](guide/pytest.md) and [machine state](guide/state.md).
- Debugging a reader? The page for [your protocol](protocols/index.md) has the byte layouts.
- Curious how it's built? [Architecture](architecture.md) and the [API reference](reference/index.md).
- Something smells wrong? Check [known issues](known-issues.md) before you lose an afternoon to it.
