"""Fault injection for outgoing replies.

Real serial lines drop bytes, double up, flip bits and take their sweet time. Your parser has to
survive all of that, and the only way to find out is to do it to it on purpose. Chaos is love.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass


@dataclass
class ChaosProfile:
    """Fault injection for outgoing bytes.

    Every rate is a probability between 0 and 1, and none of them matter unless `enabled` is True.
    Want the same disaster twice? Pass `seed`, or set MORPHEUS_VLT_CHAOS_SEED. Heads up: the seed
    goes into the global `random` module, so anything else in the process using `random` gets
    reproducible too, whether it asked or not.
    """

    enabled: bool = False

    drop_rate: float = 0.0
    duplicate_rate: float = 0.0
    corrupt_rate: float = 0.0
    flip_bit_rate: float = 0.0

    delay_ms_min: int = 0
    delay_ms_max: int = 0

    seed: int | None = None

    def __post_init__(self) -> None:
        if self.seed is None:
            env_seed = os.environ.get("MORPHEUS_VLT_CHAOS_SEED")
            self.seed = int(env_seed) if env_seed else None
        if self.seed is not None:
            random.seed(self.seed)

    def apply(self, payload: bytes) -> list[bytes]:
        """Mess with `payload` and return 0, 1 or 2 copies of whatever survived.

        The order is: drop (game over, empty list), corrupt one byte, flip one bit, sleep, then
        maybe duplicate. A duplicate is a copy of the already mangled reply, because if it's going
        to be wrong it might as well be consistently wrong.
        """
        if not self.enabled:
            return [payload]

        if self.drop_rate and random.random() < self.drop_rate:
            return []

        out = payload

        if self.corrupt_rate and len(out) and random.random() < self.corrupt_rate:
            b = bytearray(out)
            idx = random.randrange(0, len(b))
            b[idx] = (b[idx] + random.randrange(1, 255)) & 0xFF
            out = bytes(b)

        if self.flip_bit_rate and len(out) and random.random() < self.flip_bit_rate:
            b = bytearray(out)
            idx = random.randrange(0, len(b))
            bit = 1 << random.randrange(0, 8)
            b[idx] ^= bit
            out = bytes(b)

        if self.delay_ms_max or self.delay_ms_min:
            lo = max(0, self.delay_ms_min)
            hi = max(lo, self.delay_ms_max)
            delay_ms = random.randint(lo, hi)
            if delay_ms:
                time.sleep(delay_ms / 1000.0)

        bufs = [out]
        if self.duplicate_rate and random.random() < self.duplicate_rate:
            bufs.append(out)

        return bufs
