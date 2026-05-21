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
    return max(0.0, raw / 4.184)  # kJ/min → kcal/min (1 kcal = 4.184 kJ)


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
    per_min = np.clip(raw / 4.184, 0.0, None)  # kJ/min → kcal/min
    return float(np.nansum(per_min))


def coverage_pct(hr_minutes: np.ndarray) -> float:
    """Fraction of the day with non-NaN HR data, as a percentage."""
    if len(hr_minutes) == 0:
        return 0.0
    non_nan = np.isfinite(hr_minutes).sum()
    return 100.0 * non_nan / len(hr_minutes)


def daily_integral_above_baseline(
    hr_minutes: np.ndarray,
    baseline_hr: float,
    weight_kg: float,
    age: int,
    sex: str,
) -> float:
    """Activity-only kcal: integrate kcal/min ABOVE a personal resting baseline.

    Keytel's equation predicts total energy expenditure at a given HR, including
    the resting baseline metabolism that's already accounted for by Mifflin RMR.
    To separate the activity component, subtract the per-minute kcal that would
    be predicted at the user's *awake-resting* HR (the rate that already gets
    counted as RMR), then integrate the non-negative residual.

    Args:
        hr_minutes: per-minute HR array (length up to 1440). NaN where missing.
        baseline_hr: the user's awake-resting HR (e.g. mean HR during quiet
            desk hours). The per-minute kcal predicted at this HR is treated
            as the floor that already belongs to RMR.
        weight_kg, age, sex: as for kcal_per_min.

    Returns:
        Total *activity-only* kcal: sum over non-NaN minutes of
        max(0, kcal/min_at_hr - kcal/min_at_baseline).
    """
    if sex == "male":
        raw = -55.0969 + 0.6309 * hr_minutes + 0.1988 * weight_kg + 0.2017 * age
        raw_baseline = -55.0969 + 0.6309 * baseline_hr + 0.1988 * weight_kg + 0.2017 * age
    elif sex == "female":
        raw = -20.4022 + 0.4472 * hr_minutes - 0.1263 * weight_kg + 0.074 * age
        raw_baseline = -20.4022 + 0.4472 * baseline_hr - 0.1263 * weight_kg + 0.074 * age
    else:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    per_min = np.clip(raw / 4.184, 0.0, None)
    baseline_per_min = max(0.0, raw_baseline / 4.184)
    excess = np.clip(per_min - baseline_per_min, 0.0, None)
    return float(np.nansum(excess))
