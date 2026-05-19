"""Keytel HR-to-kcal equation, validated against indirect calorimetry.

Keytel et al. 2005, J Sports Sci.
"""

import numpy as np


def kcal_per_min(hr: float, weight_kg: float, age: int, sex: str) -> float:
    """Energy expenditure per minute at the given heart rate.

    Args:
        hr: heart rate in BPM
        weight_kg: body weight in kg
        age: years
        sex: "male" or "female"

    Returns:
        kcal/min, clipped to >= 0.
    """
    if sex == "male":
        raw = -55.0969 + 0.6309 * hr + 0.1988 * weight_kg + 0.2017 * age
    elif sex == "female":
        raw = -20.4022 + 0.4472 * hr - 0.1263 * weight_kg + 0.074 * age
    else:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    return max(0.0, raw / 4.184)


def daily_integral(
    hr_minutes: np.ndarray, weight_kg: float, age: int, sex: str
) -> float:
    """Integrate Keytel over a day of minute-level HR values.

    NaN values are skipped (treated as 'watch not worn'), not zeroed.

    Args:
        hr_minutes: array of HR values, one per minute, length up to 1440. NaN where missing.
        weight_kg, age, sex: as for kcal_per_min

    Returns:
        Total kcal across the non-NaN minutes.
    """
    if sex == "male":
        raw = -55.0969 + 0.6309 * hr_minutes + 0.1988 * weight_kg + 0.2017 * age
    elif sex == "female":
        raw = -20.4022 + 0.4472 * hr_minutes - 0.1263 * weight_kg + 0.074 * age
    else:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    per_min = np.clip(raw / 4.184, 0.0, None)
    return float(np.nansum(per_min))


def coverage_pct(hr_minutes: np.ndarray) -> float:
    """Fraction of the day with non-NaN HR data, as a percentage."""
    if len(hr_minutes) == 0:
        return 0.0
    non_nan = np.isfinite(hr_minutes).sum()
    return 100.0 * non_nan / len(hr_minutes)
