"""VLT protocol simulators, a.k.a. Morpheus.

Pretends to be a slot machine (Unidesa/Cirsa, SAS, VDAI, RFranco, DEX/UCS) so the reader scripts
can be tested without dragging a 90 kg cabinet into the office. Built for integration tests, dev
boxes and chaos testing, which is a fancy name for "breaking things on purpose before production
does it for free".
"""

from .core.simulator import Simulator

__all__ = ["Simulator"]
