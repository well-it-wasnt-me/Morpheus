# VDAI

The machine prints its stats like a receipt, and the reader regexes the receipt. It's exactly as robust as it
sounds.

!!! warning "Rebuilt from the reader, not from a real printout"
    Nobody had a real VDAI printout lying around. These layouts were rebuilt backwards from the reader's own
    parsing code (oblivion's `lib/protocol/vdai.py`): which lines its regex keeps, how it pulls numbers out of
    them, and which positions it reads. The labels are invented. The positions, number formats and line shapes
    are what the reader needs, and `tests/test_vdai.py` runs the reader's own expressions against the output to
    keep it that way. If you get your hands on a real capture, it beats all of this.

## Request and reply

The reader sends an ESC/P-flavored "stats" request that ends in a line feed:

```text
05 1B 53 31 32 33 34 35 36 37 38 6C 47 53 20 20 43 20 20 0A    (generic and anniversario)
05 1B 53 30 31 30 31 30 31 30 31 6C 20 53 20 20 20 20 20 0A    (bally)
```

Then it reads one byte at a time until the line goes quiet, and parses whatever it got.

The simulator answers every complete request line with one stats page. It doesn't care what the request says.
Like a support hotline. Partial requests wait for the line feed. Two requests in one read get two pages. Noise
without a line feed gets dropped after 256 bytes. And silence gets silence, which matters on a PTY where the
transport pokes the protocol with empty input every 100 ms.

Pick the flavor with `--vdai-type`: `m` generic (default), `a` anniversario, `b` bally.

## Units

Money meters are in **cents** and get printed in **euros**. Counts get printed as counts.

| Meter                                   | Kind  |
|-----------------------------------------|-------|
| `coin_in`, `bill_in`, `coin_out`, `bill_out`, `play`, `win` | money (cents) |
| `plays`                                 | count |
| `in_*`, `in_s_*`, `in_h_*`, `out_*`     | count, per denomination |
| `tot_in`, `tot_out`                     | computed: `coin_in + bill_in`, `coin_out + bill_out` |

Denominations go `10c`, `20c`, `50c`, `1e`, `2e`, `5e`, `10e`, `20e`, `50e`.

## Generic (`m`)

The reader keeps lines matching `^( < EU| +\d+$)` and pulls one number per line with `(\d+\.\d+|[^\.]\d+$)`.
So money lines need the ` < EU` prefix and a decimal point, and count lines need at least one leading space.
Lines that don't match (like the header) are ignored.

With 13 or more values, the reader reads these positions:

| Position | Meter      | Position | Meter      |
|----------|------------|----------|------------|
| 0        | `coin_in`  | 10       | `tot_out`  |
| 1        | `bill_in`  | 12       | `plays`    |
| 4        | `tot_in`   | 13       | `play`     |
| 5        | `coin_out` | 14       | `win`      |
| 6        | `bill_out` |          |            |

The simulator prints 16 values. Positions the reader never reads print `0.00`.

```text
STATISTICS
 < EU       123.45
 < EU       500.00
 < EU         0.00
 < EU         0.00
 < EU       623.45
 < EU        67.00
 < EU        20.00
 < EU         0.00
 < EU         0.00
 < EU         0.00
 < EU        87.00
 < EU         0.00
          77
 < EU      1000.00
 < EU       950.00
 < EU         0.00
```

The reader turns euros back into cents with `int(euros * 100)`, which truncates. Some amounts don't survive
the trip: 0.29 comes back as 28 cents. That's a reader bug, see [known issues](../known-issues.md). The
simulator prints the right number.

## Anniversario (`a`)

The reader keeps lines matching `(EU|.*: +[0-9]+\.*[0-9]+$)` and pulls numbers with
`([0-9]+\.[0-9]+|[0-9]+)` from the **whole line**, labels included. So:

- Labels can't contain digits. A label like `10c` would become data. The simulator spells denominations out:
  `IN TEN CENT`, `OUT FIFTY EURO`.
- Values need at least two digits after the colon, or the regex drops the line and every position after it
  shifts. Counts get zero padded: `PLAYS: 03`.
- Money goes out as euros with exactly two decimals, and the reader deletes the dot to get cents back. No
  floats involved, for once.

The page has 46 values, one per line:

| Positions | What                                                                 |
|-----------|----------------------------------------------------------------------|
| 0 to 5    | spare, the reader skips them                                         |
| 6 to 11   | `coin_in`, `bill_in`, `tot_in`, `coin_out`, `bill_out`, `tot_out`    |
| 12, 13    | spare                                                                |
| 14 to 18  | `in_s_10c`, `in_s_20c`, `in_s_50c`, `in_s_1e`, `in_s_2e`             |
| 19        | spare                                                                |
| 20 to 23  | `in_s_5e`, `in_s_10e`, `in_s_20e`, `in_s_50e`                         |
| 24 to 32  | `in_10c` through `in_50e`                                            |
| 33 to 41  | `out_10c` through `out_50e`                                          |
| 42        | spare                                                                |
| 43 to 45  | `plays`, `play`, `win`                                               |

A few lines of it:

```text
STATISTICS
SPARE: 00
...
COIN IN EU: 123.45
BILL IN EU: 500.00
TOT IN EU: 623.45
...
IN S TEN CENT: 05
...
OUT FIFTY EURO: 00
SPARE: 00
PLAYS: 03
PLAY EU: 19.99
WIN EU: 0.29
```

The reader stores the `in_h_*` counters as zeros no matter what, so the simulator doesn't print them.

## Bally (`b`)

The reader keeps lines matching `^(TOTAL PARTIDAS|PUNTOS| +\d+,\d+ =)` and pulls numbers with
`(\d+[,.]\d+|[^,.]\d+)`. That regex splits `12,00` into `12` and `00`, and a line with exactly two hits gets
divided (`second / first`). Anything else gets its first hit. So:

- Denomination lines are `count,00 = euros,cents`: four hits, the reader takes the count and never touches the
  division.
- `plays`, `play` and `win` go on lines starting with `TOTAL PARTIDAS`, `PUNTOS APOSTADOS` and
  `PUNTOS GANADOS`.
- Leading spaces are not optional. No space, no match, and every position after it shifts.

The page has 45 values. The reader deletes the 8 values right before the last 4, then zips what's left against
its counter table:

| Positions | What                                                                    |
|-----------|-------------------------------------------------------------------------|
| 0 to 7    | `in_h_2e`, `in_h_1e`, `in_h_20c`, `in_h_10c`, `in_h_50e`, `in_h_20e`, `in_h_10e`, `in_h_5e` |
| 8 to 16   | `in_s_2e`, `in_s_1e`, `in_s_50c`, `in_s_20c`, `in_s_10c`, `in_s_50e`, `in_s_20e`, `in_s_10e`, `in_s_5e` |
| 17 to 19  | `plays`, `play`, `win`                                                  |
| 20 to 28  | `in_50e`, `in_20e`, `in_10e`, `in_5e`, `in_2e`, `in_1e`, `in_50c`, `in_20c`, `in_10c` |
| 29 to 32  | `out_2e`, `out_1e`, `out_20c`, `out_10c`                                 |
| 33 to 40  | filler, deleted by the reader                                           |
| 41 to 44  | `out_50e`, `out_20e`, `out_10e`, `out_5e`                                |

The reader then works out `coin_in`, `bill_in`, `coin_out` and `bill_out` from the denomination counts. So for
Bally you set the **counts**, not the totals. Setting `coin_in` does nothing here.

With one 2-euro and two 1-euro coins in the hopper, three 50-euro bills and twelve 10-cent coins in:

```text
CONTADORES
         1,00 =         2,00
         2,00 =         2,00
...
TOTAL PARTIDAS        4321
PUNTOS APOSTADOS       98765
PUNTOS GANADOS       87654
         3,00 =       150,00
...
        12,00 =         1,20
...
```

Count first, money second. The reader only ever reads the count.

`play` and `win` go out as plain numbers. Whatever unit you put in, the reader stores.
