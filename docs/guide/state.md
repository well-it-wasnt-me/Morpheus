# Machine state

Every simulator reads its numbers from one `MachineState`. It has two buckets:

- **`counters`**: keyed by numeric id. Unidesa/Cirsa think in ids.
- **`meters`**: keyed by name. Everybody else does.

Anything you never set reads as `0`, the way a fresh machine starts and the way my bank account usually ends.

## From a JSON file

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

```bash
morpheus-vlt --protocol unidesa --state ./state.json
```

Counter ids are strings in the file because JSON says so. They turn back into ints on load. Values get run
through `int()`, so `"123"` works and `12.9` becomes `12`. Don't put money in floats. Not here, not anywhere.

Both keys are optional. Unknown keys are ignored.

## From Python

```python
from morpheus_vlt.models.state import MachineState

state = MachineState()
state.set_meter("play", 123456)
state.set_counter(1, 123456)
state.bump_counter(1, 100)      # negative works too, no questions asked
state.get_meter("nobody_set_this")  # 0
```

Hand it to the [pytest fixture](pytest.md) with `state=...`, or to a simulator directly. The simulator keeps a
reference, not a copy, so changes made during a test show up in the very next reply. That's a feature. It's
how you test a reader watching meters go up.

## Which protocol reads what

### Unidesa / Cirsa

Reads `counters`, by id. Nothing else.

The default counter list (what group `0x00` reads, and the starting custom selection) is:

```text
1, 2, 17, 3, 31, 32, 33, 34, 154, 4, 7, 8, 11, 12, 24, 35, 84, 97, 160, 161, 162, 163,
130, 131, 132, 133, 6, 80, 10, 81, 73, 114, 115, 116, 117, 122, 123, 124, 125
```

Values go out as 4 bytes, little endian, unsigned. Keep them under 4,294,967,296 or Python will tell you about
it, loudly.

### SAS

Reads `meters`. A lot of them. Most go out as BCD, so 8 digits max for a 4-byte meter. Bigger values keep only
the low digits, the same as a real meter rolling over.

Many polls take a list of names and use the first one you actually set. That's how `play` can stand in for
`coin_in`, and `win` for `coin_out`. Set the specific name if you want them to differ.

- **Core totals**: `play`, `win`, `plays`, `won`, `lost`, `drop`, `jackpot`, `cancelled_credits`, `credits`
- **Coins**: `coin_in`, `coin_out`, `true_coin_in`, `true_coin_out`, `coin_external`, `coin_hopper`
- **Bills**: `bill_in`, `bill_out`, `bill_hopper`, `bill_value_total`, `bill_credit_total`
- **Bill counts**: `bill_1` to `bill_100000` (every denomination SAS has a poll for)
- **Stacker**: `bills_in_stacker`, `bills_stacker_credit_total`
- **Last bill**: `bill_country_code`, `bill_last_denomination`, `bill_last_count`
- **Hopper**: `hopper_level`, `hopper_status`, `hopper_percent`
- **Handpay**: `handpay_amount`, `handpay_partial_amount`, `handpay_reset_id`, `hand_paid_cancelled_credit`,
  `progressive_group`, `progressive_level`
- **Doors/power**: `slot_door_opened`, `power_reset`, `games_last_power_up`, `games_since_door_closure`
- **Games**: `total_games`, `selected_game`, `features_1`, `features_2`, `features_3`
- **Cashout**: `pending_cashout_type`, `pending_cashout_amount`, `cashout_ticket_number`, `ticket_number`,
  `cashout_amount_cents`
- **Tickets**: `ticket_status`, `ticket_amount`, `ticket_parsing_code`, `ticket_validation_number`,
  `cashable_ticket_exp`, `restricted_ticket_exp`
- **Validation**: `validation_type`, `validation_index`, `validation_date`, `validation_time`, `validation_number`,
  `validation_amount`, `validation_ticket_number`, `validation_system_id`, `validation_expiration`,
  `validation_pool_id`, `validation_machine_id`, `validation_sequence`, `validation_total`,
  `validation_cumulative_amount`
- **Legacy bonus**: `legacy_deductible`, `legacy_non_deductible`, `legacy_wager_match`
- **Identity**: `asset_number`, `rom_signature`

AFT transfers (`0x72`) write to `credits`. It's the only meter any simulator changes on its own.

`asset_number` goes out as little endian binary, not BCD. Leave it unset and it's `123456789`.

The [SAS page](../protocols/sas.md) maps each command to the meters it reads.

### VDAI

Money meters are in cents and get printed in euros: `coin_in = 12345` prints as `123.45`. Counts print as
counts. What each flavor reads:

| Flavor          | Meters                                                                                   |
|-----------------|------------------------------------------------------------------------------------------|
| `m` generic     | `coin_in`, `bill_in`, `coin_out`, `bill_out`, `plays`, `play`, `win`                     |
| `a` anniversario | the same, plus denomination counts: `in_s_*`, `in_*`, `out_*`                           |
| `b` bally       | denomination counts only (`in_h_*`, `in_s_*`, `in_*`, `out_*`), plus `plays`, `play`, `win` |

Denominations go `10c`, `20c`, `50c`, `1e`, `2e`, `5e`, `10e`, `20e`, `50e`, so a full name looks like `in_10c`
or `out_50e`. `tot_in` and `tot_out` are worked out from `coin_in + bill_in` and `coin_out + bill_out`.

For Bally, the reader computes coin in, bill in, coin out and bill out itself from the denomination counts.
Setting `coin_in` does nothing there. Set the counts. The [VDAI page](../protocols/vdai.md) has the details.

### RFranco

- **`TOTALES`**: `play`, `win`, `plays`.
- **`REGISTROS`**: `bet_1` to `bet_3`, coins `in_10c`/`out_10c` through `in_2e`/`out_2e`, bills `in_5e`/`out_5e`
  through `in_50e`/`out_50e`, `in_h_5e` to `in_h_50e`, then `doorsup_c` and `doorinf_c`.
- **`ESTADO`**: `rfranco_status_1` to `rfranco_status_7`. Anything non-zero prints as `1`. Unset ones default
  to `1, 1, 0, 0, 0, 0, 0`.

The exact label for each `REGISTROS` meter is in `REGISTROS_LAYOUT`. See the [RFranco page](../protocols/rfranco.md).

### DEX / UCS

Reads nothing. It sends an EVA-DTS file, from `--dex-file` or the built-in default, and that's that. If you
want different numbers in the audit, write a different file.
