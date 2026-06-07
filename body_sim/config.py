"""User profile and literature-default constants for body_sim.

All constants here are population averages drawn from the literature, used
as priors / defaults at Phase 1. Phase 2 replaces a subset (intake_bias,
RMR_scale, etc.) with personalized posterior samples.
"""

from typing import TypedDict


class UserProfile(TypedDict):
    age: int
    sex: str  # "male" or "female"
    height_cm: float


DEFAULT_PROFILE: UserProfile = {
    "age": 40,
    "sex": "male",
    "height_cm": 180.0,
}


DEFAULT_PARAMETERS: dict[str, float] = {
    "intake_bias": 0.85,        # 15% under-reporting prior mean
    "RMR_scale": 1.0,
    "NEAT_response": 0.2,
    "protein_protection": 0.5,
    "activity_bias": 1.0,
    "water_noise_sd": 0.8,      # kg
}


TEF_COEFFICIENTS: dict[str, float] = {
    "protein": 0.25,
    "carb": 0.08,
    "fat": 0.03,
}


# Intake-completeness heuristic (foodlog-asd). A logged day counts as "complete"
# if the calories alone vouch for it OR there are enough distinct eating
# occasions — calories act as a guardrail on the meal-count proxy. This replaces
# meal-type diversity (breakfast/lunch/dinner present), which systematically
# under-read this user's fully-logged days: breakfast is logged ~53% of days
# (morning food -> "snack"), 17% of calories are "snack", and big evening meals
# are sometimes mislabeled. Meal-type labels don't affect the energy-balance fit
# (it consumes daily total intake_kcal), so completeness should track total
# calories + eating-occasion count, not label taxonomy.
#
# Grounded in the user's own daily-intake distribution (2026-06):
#   1-occasion days top out ~1060 kcal     -> always partial
#   3+-occasion days bottom out ~1470 kcal -> always full
#   2-occasion days span 700-2270 kcal     -> ambiguous; defer to the calorie floor
# These are single-user tunables; ideally they'd scale with estimated
# maintenance/TDEE once that's personalized in a later phase.
INTAKE_COMPLETE_KCAL_FLOOR: float = 1500.0
INTAKE_COMPLETE_MIN_OCCASIONS: int = 3


GLYCOGEN_WATER_G_PER_G: float = 3.5

KCAL_PER_KG_FAT: float = 9500.0
KCAL_PER_KG_LEAN: float = 7600.0

SODIUM_WATER_KG_PER_GRAM: float = 0.0001  # 0.1g water per mg sodium retained
