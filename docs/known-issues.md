# Known issues

Things that are wrong, weird, or just not done yet. Written down so you lose five minutes reading about them
instead of an afternoon finding them.

## In the simulator

**VDAI layouts are reconstructions.**
There were no real printouts to copy, so all three flavors are rebuilt backwards from the reader's parsing
code. They parse exactly right with the current reader. Whether they look anything like a real machine's
receipt is anyone's guess. A real capture (`logs/vdai_*.txt` from a reader in the field) would settle it.

**Unidesa over TCP: one client at a time.**
The request handler keeps one stream buffer per server, not per connection. Two clients sending partial frames
at the same moment would get their bytes mixed. The readers connect one at a time, so it hasn't come up.

**DEX CRC skips every `0x10`.**
Including one that's real data and not framing. EVA-DTS files are printable ASCII, so it hasn't mattered. A
binary-ish file would get a CRC the reader disagrees with.

**SAS AFT reply has a zero length byte.**
Payload byte 0 of the `0x72` reply should be the number of bytes that follow. It's `0x00`. The readers don't
look at it.

**SAS is shallow on purpose.**
Every game reports the machine-wide meters. `0x2F` ignores which meters were asked for. Machine identity, ticket
replies and validation are mostly hardcoded or read straight from meters with no logic behind them.

**The pytest fixture can't load a DEX file.**
DEX always gets the built-in EVA-DTS file there. The CLI has `--dex-file`.

**Chaos seeds the global `random`.**
A `seed` or `MORPHEUS_VLT_CHAOS_SEED` makes everything else in the process using `random` reproducible too.

**No PTYs on Windows.**
TCP only. Windows and PTYs have never been on speaking terms.

## In the readers

These are bugs in the reader scripts the simulator talks to, found while making the simulator satisfy them.
The simulator prints the right numbers. The reader gets some of them wrong.

**VDAI generic: `int(euros * 100)` truncates.**
Floats can't hold most decimal amounts exactly, and `int()` rounds toward zero. 0.29 EUR is stored as 28
cents, 0.57 as 56, 1.15 as 114, 19.99 as 1998. `round()` instead of `int()` would fix it.

**VDAI anniversario: single-digit values vanish.**
The regex needs at least two digits after the colon. A real machine printing `PLAYS: 3` would have that line
dropped, and every position after it would shift by one. The simulator zero pads, so it doesn't trigger this.

**VDAI bally: lines with exactly two numbers get divided.**
The number regex splits `12,00` into `12` and `00`. A line with exactly two hits gets `second / first`, so a
line like `   0,00 =` with nothing after it would raise `ZeroDivisionError`. The simulator always prints four
numbers per line, so it doesn't trigger this.

## Fixed

| Date       | What was wrong                                                                                   |
|------------|--------------------------------------------------------------------------------------------------|
| 2026-10-27 | DEX: a first-handshake request split across two reads was thrown away. The reader got silence.   |
| 2026-10-27 | SAS `0x18`: games since power up got overwritten, and games since door closure was never sent.   |
| 2026-10-27 | SAS asset number: a configured `asset_number` went out as BCD instead of little endian binary.    |
| 2026-10-27 | SAS AFT: the transfer code was read as the transfer type, so every cash-out added credits.       |
| 2026-10-27 | SAS AFT: the status poll reported 0 instead of the last transfer's amount.                       |
| 2026-10-27 | VDAI: none of the three flavors parsed with the real reader.                                     |
| 2026-10-27 | VDAI: on a PTY it sent a stats page every 100 ms without being asked.                            |
| 2026-10-27 | Pytest fixture, Unidesa on a PTY: the first idle tick crashed the server thread.                 |
| 2026-10-27 | Pytest fixture: didn't split Unidesa frames or catch protocol errors the way the CLI does.       |
| 2026-10-27 | Pytest fixture: returned before the server was listening, so the first connect could fail.      |
