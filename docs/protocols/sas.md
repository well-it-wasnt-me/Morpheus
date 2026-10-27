# SAS

Slot Accounting System. The big one. Real SAS runs on a 9-bit serial line where the ninth bit marks the address
byte. A PTY or a TCP socket has eight bits and no opinion about it, so the electrical part isn't emulated. What
is emulated: correctly sized replies, BCD meters at the offsets the readers slice, and a CRC that saspy agrees
with. The readers count bytes and cut at fixed offsets, so getting the sizes right is 90% of the job. The other
10% is also getting the sizes right.

## Requests

No ninth bit, so the readers fake the wake-up with a marker byte. All of these work:

```text
82 01 0F       marker, address, command
80 01 0F       other marker, address, command
01 0F          address, command
0F             just the command
```

The machine address defaults to `0x01`. Change it with `--sas-addr`.

One request per read, no buffering. SAS hosts send a request and wait for the answer, so that's what they get.

## Replies

```text
ADDR  CMD  PAYLOAD...  CRC_LO  CRC_HI
```

The total length is fixed per command, and it's the number the reader passes to `read()`. One byte off and the
reader sits there until it times out.

### CRC

CRC-16/KERMIT: polynomial `0x1021` bit-reversed (`0x8408`), initial value 0, low byte first on the wire. The
check value for `"123456789"` is `0x2189`, sent as `89 21`. Same as saspy, which is the point.

### BCD

Most meters go out as BCD, two decimal digits per byte. `1234` in 4 bytes is `00 00 12 34`. A meter too big for
its field keeps only the low digits, same as a real meter rolling over. Negative becomes 0.

## A real exchange

With `play = 1000`, `win = 2000`, `plays = 77`:

```text
->  82 01 0F
<-  01 0F 00 00 00 00 00 00 10 00 00 00 20 00 00 00 00 00 00 00 00 00 00 00 00 77 E1 A7
```

28 bytes: address, command, six 4-byte BCD meters (cancelled credits, coin in, coin out, drop, jackpot, games
played), CRC. `play` stood in for coin in and `win` for coin out, because nobody set those.

## Commands

### Acks and polls

- **General poll**, `0x80` or `0x80 + addr`: 1 byte, `00`, "no events". The most honest thing a machine says.
- **Ack-only**, `0x01` to `0x0B`, `0x0E`, `0x2E`, `0x7F`, `0x8A`, `0x8B`, `0x8C`, `0x94`, `0xAA`: 1 byte, the
  machine address. Shutdown, startup, sound, bill acceptor on/off, maintenance mode and friends. The host
  barks, the machine nods.

### Meters

Meter names in parentheses are tried in order. The first one you actually set wins.

| Command | Length | Contents |
|---------|--------|----------|
| `0x0F`  | 28 | `cancelled_credits`, (`play`, `coin_in`), (`win`, `coin_out`), `drop`, `jackpot`, `plays` |
| `0x10` to `0x4A` | 8 | One 4-byte BCD meter. See the table below. |
| `0x18`  | 8  | `games_last_power_up`, `games_since_door_closure`, 2 BCD bytes each |
| `0x19`  | 24 | `play`, `win`, (`coin_in`, `play`), `jackpot`, `plays` |
| `0x1C`  | 36 | `play`, `win`, `drop`, `jackpot`, `plays`, `won`, `slot_door_opened`, `power_reset` |
| `0x1E`  | 28 | `bill_1`, `bill_5`, `bill_10`, `bill_20`, `bill_50`, `bill_100` |
| `0x2F`  | 57 | Ten `(code, 4-byte BCD)` blocks, always the same ten. See below. |
| `0x52`  | 22 | Game number, then `play`, `win`, `jackpot`, `plays`. Every game reports the machine-wide meters. |
| `0x9A`  | 18 | `legacy_deductible`, `legacy_non_deductible`, `legacy_wager_match` |

Single meter polls:

| Command | Meter | Command | Meter |
| --- | --- | --- | --- |
| `0x10` | `cancelled_credits` | `0x2D` | `hand_paid_cancelled_credit` |
| `0x11` | (`play`, `coin_in`) | `0x31` to `0x45` | `bill_*`, one per denomination (below) |
| `0x12` | (`win`, `coin_out`) | `0x46` | `bill_credit_total` |
| `0x13` | `drop` | `0x47` | `coin_external` |
| `0x14` | `jackpot` | `0x49` | `bills_in_stacker` |
| `0x15` | `plays` | `0x4A` | `bills_stacker_credit_total` |
| `0x16` | `won` | `0x20` | (`bill_value_total`, `bill_in`) |
| `0x17` | `lost` | `0x2A` | (`true_coin_in`, `coin_in`, `play`) |
| `0x1A` | `credits` | `0x2B` | (`true_coin_out`, `coin_out`, `win`) |

The bill polls skip `0x3D`, which is the cashout ticket. In order: `0x31` `bill_1`, `0x32` `bill_2`, `0x33`
`bill_5`, `0x34` `bill_10`, `0x35` `bill_20`, `0x36` `bill_50`, `0x37` `bill_100`, `0x38` `bill_500`, `0x39`
`bill_1000`, `0x3A` `bill_200`, `0x3B` `bill_25`, `0x3C` `bill_2000`, `0x3E` `bill_2500`, `0x3F` `bill_5000`,
`0x40` `bill_10000`, `0x41` `bill_20000`, `0x42` `bill_25000`, `0x43` `bill_50000`, `0x44` `bill_100000`, `0x45`
`bill_250`. The order is SAS's idea, not mine.
|  |  | `0x2C` | (`hopper_level`, `coin_hopper`) |

`0x2F` ignores which meters the request asks for and always sends these ten, because they're the ten the reader
always asks for. If the reader ever changes its mind, the simulator will be the last to know.

| Code | Meter               | Code | Meter                |
|------|---------------------|------|----------------------|
| 0    | `play`              | 9    | (`coin_out`, `win`)  |
| 1    | `win`               | 10   | `coin_hopper`        |
| 5    | `plays`             | 11   | `bill_in`            |
| 6    | `won`               | 88   | `bill_hopper`        |
| 8    | (`coin_in`, `play`) | 110  | `bill_out`           |

### Machine info

| Command | Length | Contents |
| --- | --- | --- |
| `0x1F` | 24 | Machine id and info. Hardcoded, because the machine is also fake. See below. |
| `0x21` | 6 | `rom_signature`, 2 bytes big endian. No math. |
| `0x51` | 6 | `total_games`, at least 1. An empty cabinet is just furniture. |
| `0x53` | 26 | Game N configuration. The `0x1F` identity with the requested game number in front. |
| `0x54` | 20 | SAS version `6.03`, serial `SIM000000001` |
| `0x55` | 6 | `selected_game`, defaults to 1 |
| `0x56` | 8 | Enabled games: exactly one, the selected one |
| `0x6E` | 10 | Authentication info: one component, nothing to authenticate. Trust me. |
| `0x7E` | 11 | Local date and time, BCD `MMDDYYYYHHMMSS`. The only thing in here that isn't made up. |
| `0xA0` | 12 | Enabled features for game N, from `features_1` to `features_3` |

The `0x1F` identity: game id `GM`, additional id `001`, denomination code `01`, max bet 100, no progressive
group, paytable `P00001`, base payback `9500`. That's 95.00%. The house thanks you.

### Tickets, validation, handpay

- `0x1B` (24 bytes), handpay: `progressive_group`, `progressive_level`, `handpay_amount`,
  `handpay_partial_amount`, `handpay_reset_id`.
- `0x3D` (13): cashout ticket. (`cashout_ticket_number`, `ticket_number`), then (`cashout_amount_cents`,
  `pending_cashout_amount`, `credits`).
- `0x48` (10): last accepted bill. `bill_country_code`, `bill_last_denomination`, `bill_last_count`.
- `0x4C` (11): `validation_machine_id`, `validation_sequence`. The request is ignored.
- `0x4D` (35): one enhanced validation record, every field from a `validation_*` meter.
- `0x4F` (11): hopper. `hopper_status`, `hopper_percent`, (`hopper_level`, `coin_hopper`).
- `0x50` (14): echoes the validation type, then `validation_total`, `validation_cumulative_amount`.
- `0x57` (10): pending cashout. `pending_cashout_type`, (`pending_cashout_amount`, `credits`).
- `0x58` (5): status `00`, accepted. The number goes straight in the trash.
- `0x70` (20): ticket validation data. `ticket_status`, (`ticket_amount`, `pending_cashout_amount`),
  `ticket_parsing_code`, `ticket_validation_number`.
- `0x71` (20): redeem ticket. Status `00`, it worked. No credits move. It's a demo.
- `0x7B` (15): extended validation status. Asset number, `cashable_ticket_exp`, `restricted_ticket_exp`.

### AFT

AFT (Advanced Funds Transfer) is the one corner of the simulator that changes state: transfers move the
`credits` meter, so a test can push money in and watch it land. Then take it out. The machine always wins,
even the fake one.

**`0x72` transfer funds.** The request carries the fields in this order, after the command byte:

| Request byte | Field                  |
|--------------|------------------------|
| 1            | length                 |
| 2            | transfer code          |
| 3            | transaction index      |
| 4            | transfer type          |
| 5 to 9       | cashable amount, BCD   |
| 10 to 14     | restricted amount, BCD |
| 15 to 19     | non-restricted amount, BCD |
| 20           | transfer flags         |
| 21 to 24     | asset number           |
| 25 to 44     | registration key       |
| 45           | transaction ID length  |
| 46 and up    | transaction ID         |

The **transfer code** says what to do with the request:

- `0x00` (full) or `0x01` (partial): move the money.
- `0xFF`: don't move anything, report the last transfer. That's the status poll.
- anything else (like `0x80`, cancel): move nothing, report the last transfer.

The **transfer type** says which way the money goes:

- `0x00`, `0x10`, `0x11` (in-house, bonus coin out, bonus jackpot): the cashable amount gets added to `credits`.
- `0x80`, `0x90` (in-house to host, win to host): it gets taken out, floored at zero. The machine doesn't do loans.

The reply is 82 bytes and always says the transfer succeeded, which is more than most banks will do for you.
It reports the last real transfer: its type at payload byte 4, the three amounts, the asset number, the
transaction ID and the current date and time. A status poll right after a transfer reads the amount that just
moved, which is exactly where the jupiter-os reader looks for it.

The transaction ID gets remembered from the request (its length byte is looked for at offset 60, then 45).
Before the first transfer it's fifteen spaces and an exclamation mark. Somebody's idea of a placeholder.

**`0x73` register.** Code `0x80` unregisters, anything else registers. No paperwork. 34 bytes.

**`0x74` lock and status.** Lock code `0x80` reports `0xFF` (not locked), anything else reports `0x00`
(locked). The current `credits` go in the cashable slot, the other balances are zero. 40 bytes.

### Asset number

4 bytes, little endian binary. Not BCD, for once. It comes from the `asset_number` meter, or `123456789` if you
never set one (`15 CD 5B 07` on the wire). The readers build it the same way: asset 1 is `01 00 00 00`.

### Anything else

`0xFF` followed by zeros, padded to the length the reader expects for that command, or 8 bytes if the simulator
has never heard of it. Not a real answer, but it's the right size, and with these readers that's most of the
war.

## Idle line

On a PTY, until the host sends anything, the simulator announces its address byte on the idle line, at most
every 0.5 seconds. The first real request shuts that off for good. pyserial flushes the input buffer when it
opens the port, so those bytes don't end up in front of your first reply.
