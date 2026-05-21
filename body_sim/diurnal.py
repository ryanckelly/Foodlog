"""Diurnal mass-dynamics model.

Decomposes the morning→evening weight delta into three additive components:
- **food-in-transit** (positive): today's intake hasn't fully been excreted by evening
- **sodium-driven extra water** (positive): today's sodium peaks at PM
- **sweat deficit** (negative): vigorous activity without full rehydration

These are first-order approximations matching published GI-transit,
sodium-balance, and sweat-rate literature. Real PM weight has additional
sources of variance (drink timing, ambient temperature, stress cortisol)
that this model doesn't try to predict.

Used by:
- ``model.BodyState.predicted_evening_weight_kg`` to produce a PM observation
  expectation.
- (future Phase-3.1 work) the Bayesian fit to add a deterministic-mean term
  to a diurnal latent.
"""

from body_sim.config import SODIUM_WATER_KG_PER_GRAM


FOOD_TRANSIT_FRACTION_AT_EVENING: float = 0.50
KCAL_PER_G_FOOD: float = 3.0
SWEAT_KG_PER_VIGOROUS_HOUR: float = 0.50
SWEAT_KG_PER_WORKOUT_HOUR: float = 0.20
BASELINE_SODIUM_MG: float = 2300.0
# Today's PM sodium-water is roughly equal to the daily-equilibrium value;
# overnight excretion removes ~70% by next morning. The next-morning carryover
# is modeled upstream by the standing sodium.water_kg model — here we only
# capture the same-day PM peak relative to morning baseline.
SODIUM_PM_SCALE: float = 1.0
# Wash-out factor: assumes user doesn't fully rehydrate by evening
SWEAT_REHYDRATION_FACTOR: float = 0.7


def food_in_transit_kg(intake_kcal: float) -> float:
    """Mass of food + water from today's intake still in the GI tract at evening."""
    if intake_kcal <= 0:
        return 0.0
    food_mass_g = intake_kcal / KCAL_PER_G_FOOD
    return FOOD_TRANSIT_FRACTION_AT_EVENING * food_mass_g / 1000.0


def sweat_kg(workout_min: int, vigorous_min: int) -> float:
    """Net evening-time sweat deficit from today's activity, in kg."""
    raw = (
        SWEAT_KG_PER_WORKOUT_HOUR * (workout_min / 60.0)
        + SWEAT_KG_PER_VIGOROUS_HOUR * (vigorous_min / 60.0)
    )
    return max(0.0, raw * SWEAT_REHYDRATION_FACTOR)


def sodium_pm_water_kg(sodium_mg: float) -> float:
    """Water mass from today's sodium that's in evening but not morning."""
    excess = max(0.0, sodium_mg - BASELINE_SODIUM_MG)
    return SODIUM_PM_SCALE * SODIUM_WATER_KG_PER_GRAM * excess


def predicted_diurnal_delta_kg(
    intake_kcal: float, sodium_mg: float,
    workout_min: int, vigorous_min: int,
) -> float:
    """Expected morning→evening weight delta in kg.

    delta = food_in_transit + sodium_pm_water - sweat
    """
    return (
        food_in_transit_kg(intake_kcal)
        + sodium_pm_water_kg(sodium_mg)
        - sweat_kg(workout_min, vigorous_min)
    )
