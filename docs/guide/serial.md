# Fake serial ports

The readers talk serial. Real machines hang off RS-232 or RS-485 adapters with names like `/dev/ttyUSB0`. A
PTY (pseudo-terminal) is a serial port that isn't there: the kernel hands out two ends, Morpheus holds one,
your reader opens the other, and pyserial can't tell the difference. Neither can your reader. Neither could I,
the first time.

Linux and macOS only. Windows and PTYs have never been on speaking terms.

## Starting one

```bash
morpheus-vlt --protocol sas --transport pty --tty-name ttySAS
```

```text
INFO:morpheus-vlt:Listening on PTY /tmp/ttySAS (sas)
INFO:morpheus-vlt:PTY ready: /dev/pts/7 (link: /tmp/ttySAS)
```

The real device is `/dev/pts/7`, and that number changes every run. The symlink `/tmp/ttySAS` doesn't. Point
your reader at the symlink and stop caring about the number.

## Where the symlink goes

| You pass                          | You get                                        |
|-----------------------------------|------------------------------------------------|
| `--tty-path /some/where/ttyX`     | `/some/where/ttyX`. Wins over everything else. |
| `--tty-name ttyX`                 | `/tmp/ttyX`                                    |
| `--tty-name ttyX --tty-dir /run`  | `/run/ttyX`                                    |
| nothing                           | No symlink. A bare `/dev/pts/<n>`, printed in the log. Good luck remembering it. |

Putting the symlink under `/dev` (say, `--tty-path /dev/ttyUSB9` so a reader with a hardcoded path is happy)
needs write permission there, which usually means root. Your call. I'm not your sysadmin.

## The symlink is careful

- A stale symlink from a previous run gets replaced.
- Something at that path that is **not** a symlink is left alone, and startup fails with `FileExistsError`.
  Nobody wants to explain why `/dev/ttyS0` vanished.
- On shutdown the symlink gets removed. It leaves the campsite cleaner than it found it.

## What the PTY does for you

- **Raw mode**: the slave end is set raw, so no line editing, no echo, no translating `\r` into `\n` behind
  your back. Bytes go through exactly as sent. Same as a real serial line, minus the noise.
- **Baud rate is ignored**: set 9600, 19200, 115200, whatever your reader sets. The PTY won't argue. There's
  no wire, so there's nothing to clock.
- **Idle ticks**: when nothing arrives for 100 ms, the protocol gets called with no data, so it can speak up
  unprompted. Only SAS uses this. It announces its address byte, at most every 0.5 s, until the host says
  something. Everybody else stays quiet.

!!! note "No ninth bit"
    SAS on real hardware uses a 9-bit serial mode where the ninth bit flags the address byte. A PTY has eight
    bits and no opinion about it. Readers fake the wake-up with an `0x80` or `0x82` byte in front of the
    address. See the [SAS page](../protocols/sas.md).

## Talking to it from Python

```python
import serial

ser = serial.Serial("/tmp/ttySAS", baudrate=9600, timeout=1)
ser.write(bytes([0x82, 0x01, 0x0F]))  # wake-up marker, address, command
resp = ser.read(28)                    # 0x0F replies are always 28 bytes
print(resp.hex())
ser.close()
```

pyserial clears the input buffer when it opens the port, so any address bytes SAS announced before you showed
up don't end up in front of your reply. If you open the device some other way, flush it yourself.

## Talking to it by hand

The ASCII protocols are easier to poke at with a terminal. pyserial ships one:

```bash
morpheus-vlt --protocol rfranco --transport pty --tty-name ttyRF
python -m serial.tools.miniterm /tmp/ttyRF 9600 --eol CRLF
```

Type `ESTADO`, hit Enter, watch it answer. Type `C`, then `RF`, then `REGISTROS`. It's the closest thing to a
conversation this project has.
