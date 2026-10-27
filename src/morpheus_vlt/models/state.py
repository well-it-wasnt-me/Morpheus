"""The machine's numbers. Not real money, so for once nobody gets audited."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MachineState:
    """Generic numeric counters for a VLT.

    Two buckets: `counters` keyed by numeric id (Unidesa/Cirsa think in ids) and `meters` keyed by
    name (everybody else does). Anything you never set reads as 0, the way a fresh machine starts
    and the way my bank account usually ends.
    """

    counters: dict[int, int] = field(default_factory=dict)  # id -> value
    meters: dict[str, int] = field(default_factory=dict)    # name -> value

    def get_counter(self, counter_id: int) -> int:
        """Return counter `counter_id`, or 0 if nobody ever set it."""
        return int(self.counters.get(counter_id, 0))

    def set_counter(self, counter_id: int, value: int) -> None:
        """Overwrite counter `counter_id` with `value`."""
        self.counters[counter_id] = int(value)

    def bump_counter(self, counter_id: int, delta: int) -> None:
        """Add `delta` to counter `counter_id`. Negative works too, no questions asked."""
        self.counters[counter_id] = self.get_counter(counter_id) + int(delta)

    def get_meter(self, name: str) -> int:
        """Return meter `name`, or 0 if nobody ever set it."""
        return int(self.meters.get(name, 0))

    def set_meter(self, name: str, value: int) -> None:
        """Overwrite meter `name` with `value`."""
        self.meters[name] = int(value)
