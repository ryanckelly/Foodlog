"""Resting metabolic rate (RMR) via Mifflin-St Jeor.

Mifflin et al. 1990, Am J Clin Nutr.
"""


def mifflin_st_jeor(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    """Mifflin-St Jeor RMR in kcal/day.

    Args:
        weight_kg: total body weight (fat + lean + water) in kg
        height_cm: standing height in cm
        age: years
        sex: "male" or "female"

    Returns:
        Predicted RMR in kcal/day.
    """
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
