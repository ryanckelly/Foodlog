"""Sodium-bound water retention.

Excess sodium intake above the dietary baseline drives transient water retention
(typical: 100-300 mg water per excess mg sodium). This is a first-order model
of a complex renal process — good enough to explain the 1-2 lb scale jump after
a high-sodium meal but not a clinical sodium-balance model.
"""

from body_sim.config import SODIUM_WATER_KG_PER_GRAM

BASELINE_SODIUM_MG = 2300.0  # WHO-recommended daily intake


def water_kg(sodium_mg: float) -> float:
    """Extra water retention in kg given today's sodium intake."""
    excess_mg = max(0.0, sodium_mg - BASELINE_SODIUM_MG)
    return SODIUM_WATER_KG_PER_GRAM * excess_mg
