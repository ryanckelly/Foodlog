"""SQLite-to-pandas daily-rollup pipeline for body_sim.

Single entry point: `build_daily_rollup(session, start, end)`. Internally
composed of per-source helpers (rollup_food, rollup_activity, etc.) so each is
independently testable.

All helpers return a DataFrame indexed by date with one row per day in
[start, end] inclusive — missing days are present with NaN/zero per the
missingness conventions in the spec.
"""

import datetime

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from foodlog.db.models import DailyActivity, FoodEntry, IntervalAzm, IntervalHeartRate

from body_sim import keytel


def _date_index(start: datetime.date, end: datetime.date) -> pd.DatetimeIndex:
    """Daily index covering [start, end] inclusive."""
    return pd.date_range(start=start, end=end, freq="D", name="date")


def rollup_food(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    """Aggregate `food_entries` to one row per day with intake totals + coverage.

    Columns returned:
        intake_kcal       — total calories (NaN if no entries that day)
        protein_g         — total protein (NaN if no entries)
        carb_g            — total carbohydrate (NaN if no entries)
        fat_g             — total fat (NaN if no entries)
        sodium_mg         — total sodium (NaN if no entries)
        meal_types_logged — frozenset of meal_type strings present
        intake_coverage   — fraction of {breakfast, lunch, dinner} logged (0.0–1.0)
        intake_logged     — True if coverage >= 0.67

    Snacks are included in calorie/macro totals but are excluded from the
    coverage calculation (coverage counts only the three main meal types).

    If the same meal_type is logged twice on the same day both rows contribute
    to calorie/macro sums and the meal_type is counted once for coverage — the
    GROUP BY collapses duplicate meal_types correctly.

    Note: uses func.date() rather than cast(Date) because SQLite's DATE cast
    returns a numeric tuple in SQLAlchemy's in-memory driver, making it
    unusable for string comparison. func.date() returns an ISO-8601 string
    ('YYYY-MM-DD') on both SQLite and PostgreSQL and is safe for >= / <=
    comparisons against isoformat() strings.
    """
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    rows = (
        session.query(
            func.date(FoodEntry.logged_at).label("d"),
            FoodEntry.meal_type,
            func.sum(FoodEntry.calories).label("kcal"),
            func.sum(FoodEntry.protein_g).label("p"),
            func.sum(FoodEntry.carbs_g).label("c"),
            func.sum(FoodEntry.fat_g).label("f"),
            func.sum(FoodEntry.sodium_mg).label("na"),
            func.count().label("n"),
        )
        .filter(
            func.date(FoodEntry.logged_at) >= start_iso,
            func.date(FoodEntry.logged_at) <= end_iso,
        )
        .group_by("d", FoodEntry.meal_type)
        .all()
    )

    # Build per-day aggregates
    per_day: dict[datetime.date, dict] = {}
    for r in rows:
        d = r.d if isinstance(r.d, datetime.date) else datetime.date.fromisoformat(str(r.d))
        cell = per_day.setdefault(
            d,
            {
                "intake_kcal": 0.0,
                "protein_g": 0.0,
                "carb_g": 0.0,
                "fat_g": 0.0,
                "sodium_mg": 0.0,
                "meal_types_logged": set(),
                "n_entries": 0,
            },
        )
        cell["intake_kcal"] += r.kcal or 0
        cell["protein_g"] += r.p or 0
        cell["carb_g"] += r.c or 0
        cell["fat_g"] += r.f or 0
        cell["sodium_mg"] += r.na or 0
        cell["meal_types_logged"].add(r.meal_type)
        cell["n_entries"] += r.n

    # Materialize one row per day in the requested range
    idx = _date_index(start, end)
    records = []
    for ts in idx:
        d = ts.date()
        if d in per_day:
            cell = per_day[d]
            main_meals = {"breakfast", "lunch", "dinner"} & cell["meal_types_logged"]
            coverage = len(main_meals) / 3.0
            records.append(
                {
                    "intake_kcal": cell["intake_kcal"],
                    "protein_g": cell["protein_g"],
                    "carb_g": cell["carb_g"],
                    "fat_g": cell["fat_g"],
                    "sodium_mg": cell["sodium_mg"],
                    "meal_types_logged": frozenset(cell["meal_types_logged"]),
                    "intake_coverage": coverage,
                    "intake_logged": bool(coverage >= 0.67),
                }
            )
        else:
            records.append(
                {
                    "intake_kcal": np.nan,
                    "protein_g": np.nan,
                    "carb_g": np.nan,
                    "fat_g": np.nan,
                    "sodium_mg": np.nan,
                    "meal_types_logged": frozenset(),
                    "intake_coverage": 0.0,
                    "intake_logged": False,
                }
            )
    df = pd.DataFrame(records, index=idx)
    # Preserve Python bool identity so `row["intake_logged"] is True/False`
    # works in tests. pandas infers bool dtype → np.bool_, which fails `is`
    # checks. Cast to object dtype to keep the native Python bool objects.
    df["intake_logged"] = df["intake_logged"].astype(object)
    return df


def rollup_activity(
    session: Session,
    start: datetime.date,
    end: datetime.date,
    weight_kg: float,
    age: int,
    sex: str,
) -> pd.DataFrame:
    """Aggregate activity sources to one row per day.

    Columns: steps, active_kcal_fitbit, ee_hr_keytel_kcal, hr_coverage_pct,
    vigorous_min, cardio_min.

    HR coverage is computed by placing the collected bpm_avg values into a
    1440-slot array (one slot per minute of the day) starting at index 0.
    This works correctly when the source data is already stored at minute
    resolution (one row per minute), which is the Fitbit/Pixel Watch convention
    used in this project.  If future sources have coarser intervals, the
    coverage calculation will need revisiting.

    Like rollup_food, this function uses datetime comparisons directly on
    DateTime columns (no func.date() needed) because the filter is an
    inequality on a full datetime, not a string-based date comparison.
    """
    idx = _date_index(start, end)
    records = {ts.date(): _empty_activity_row() for ts in idx}

    # --- Daily activity (Fitbit rollup) ---
    da_rows = (
        session.query(DailyActivity)
        .filter(DailyActivity.date >= start, DailyActivity.date <= end)
        .all()
    )
    for r in da_rows:
        cell = records[r.date]
        cell["steps"] = r.steps
        cell["active_kcal_fitbit"] = r.active_calories_kcal

    # --- AZM intervals (active zone minutes) ---
    azm_rows = (
        session.query(IntervalAzm)
        .filter(
            IntervalAzm.start_at >= datetime.datetime.combine(start, datetime.time()),
            IntervalAzm.start_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .all()
    )
    for r in azm_rows:
        d = r.start_at.date()
        cell = records[d]
        cell["cardio_min"] += r.cardio_min or 0
        cell["vigorous_min"] += r.peak_min or 0  # peak = vigorous in our convention

    # --- HR intervals → daily Keytel EE + coverage ---
    hr_rows = (
        session.query(IntervalHeartRate)
        .filter(
            IntervalHeartRate.start_at >= datetime.datetime.combine(start, datetime.time()),
            IntervalHeartRate.start_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .all()
    )
    per_day_hr: dict[datetime.date, list[int]] = {ts.date(): [] for ts in idx}
    for r in hr_rows:
        per_day_hr[r.start_at.date()].append(r.bpm_avg)

    for d, bpms in per_day_hr.items():
        if not bpms:
            continue
        # Place collected bpms into a 1440-slot (minutes-in-day) NaN array.
        # Slots beyond len(bpms) remain NaN → coverage_pct counts them as missing.
        arr = np.full(1440, np.nan)
        arr[: len(bpms)] = bpms
        cell = records[d]
        cell["ee_hr_keytel_kcal"] = keytel.daily_integral(
            arr, weight_kg=weight_kg, age=age, sex=sex
        )
        cell["hr_coverage_pct"] = keytel.coverage_pct(arr)

    df = pd.DataFrame([records[ts.date()] for ts in idx], index=idx)
    return df


def _empty_activity_row() -> dict:
    return {
        "steps": np.nan,
        "active_kcal_fitbit": np.nan,
        "ee_hr_keytel_kcal": np.nan,
        "hr_coverage_pct": 0.0,
        "vigorous_min": 0,
        "cardio_min": 0,
    }
