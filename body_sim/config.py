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


GLYCOGEN_WATER_G_PER_G: float = 3.5

KCAL_PER_KG_FAT: float = 9500.0
KCAL_PER_KG_LEAN: float = 7600.0

SODIUM_WATER_KG_PER_GRAM: float = 0.0001  # 0.1g water per mg sodium retained
