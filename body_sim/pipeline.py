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

from body_sim import baseline, keytel

from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    FoodEntry,
    IntervalAzm,
    IntervalHeartRate,
    RestingHeartRate,
    SleepSession,
    Workout,
)


# Body-composition readings excluded from body_sim analysis because they
# don't match the user's normal weigh-in methodology (e.g. taken with
# clothes on, off the regular morning-routine time-of-day).
# DB rows themselves are not deleted by this filter — these are only
# excluded from the body_sim pipeline so the dashboard / MCP tools remain
# unaffected. See body_sim/CLAUDE.md for details on each exclusion.
EXCLUDED_BODY_COMP_IDS: frozenset[str] = frozenset(
    {
        "users/7108215177813058725/dataTypes/weight/dataPoints/1777669898000",
        "users/7108215177813058725/dataTypes/weight/dataPoints/1777824995000",
    }
)


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
    baseline_hr: float | None = None,
) -> pd.DataFrame:
    """Aggregate activity sources to one row per day.

    Columns: steps, active_kcal_fitbit, ee_hr_keytel_kcal, hr_coverage_pct,
    vigorous_min, cardio_min.

    HR coverage is computed by placing each bpm_avg value into the 15 slots
    (minutes) of the 1440-slot array that correspond to the row's window,
    using the row's start_at minute-of-day as the start slot.  This matches
    the 15-min rollUp cadence of Google Health v4 / Pixel Watch IntervalHeartRate
    rows.  If future sources have different cadences, adjust INTERVAL_MIN inside
    the HR block below.

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
    # IntervalHeartRate rows arrive at 15-min spacing from Google Health v4 rollUp
    # (see docs/superpowers/specs/2026-05-01-foodlog-granular-timeline-design.md).
    # Each row's bpm_avg is the average across a 15-min window starting at start_at.
    INTERVAL_MIN = 15

    per_day_hr: dict[datetime.date, list[tuple[int, int]]] = {ts.date(): [] for ts in idx}
    for r in hr_rows:
        minute_of_day = r.start_at.hour * 60 + r.start_at.minute
        per_day_hr[r.start_at.date()].append((minute_of_day, r.bpm_avg))

    for d, samples in per_day_hr.items():
        if not samples:
            continue
        arr = np.full(1440, np.nan)
        for minute_of_day, bpm in samples:
            # Each 15-min window fills its 15 slots
            start_slot = minute_of_day
            end_slot = min(1440, minute_of_day + INTERVAL_MIN)
            arr[start_slot:end_slot] = bpm
        cell = records[d]
        if baseline_hr is None:
            cell["ee_hr_keytel_kcal"] = keytel.daily_integral(
                arr, weight_kg=weight_kg, age=age, sex=sex
            )
        else:
            cell["ee_hr_keytel_kcal"] = keytel.daily_integral_above_baseline(
                arr, baseline_hr=baseline_hr, weight_kg=weight_kg, age=age, sex=sex
            )
        cell["hr_coverage_pct"] = keytel.coverage_pct(arr)
        cell["keytel_baseline_bpm"] = float("nan") if baseline_hr is None else float(baseline_hr)

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
        "keytel_baseline_bpm": np.nan,
    }


def rollup_body_comp(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    """Aggregate body_composition to one row per day.

    Columns:
        weight_kg                       median of all non-excluded readings
        bf_pct                          median of all non-excluded readings
        n_weighins                      count of non-excluded readings
        weigh_in_protocol_controlled    True iff every non-excluded reading
                                        that day is tagged ``controlled_morning``

    Multiple readings on the same day are reduced to the median for both
    weight and body-fat percentage. Days with no readings return NaN for
    weight_kg/bf_pct, 0 for n_weighins, False for the protocol flag.
    """
    rows = (
        session.query(BodyComposition)
        .filter(
            BodyComposition.measured_at >= datetime.datetime.combine(start, datetime.time()),
            BodyComposition.measured_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
            ~BodyComposition.external_id.in_(EXCLUDED_BODY_COMP_IDS),
        )
        .all()
    )
    per_day: dict[datetime.date, list[BodyComposition]] = {}
    for r in rows:
        per_day.setdefault(r.measured_at.date(), []).append(r)

    idx = _date_index(start, end)
    records = []
    for ts in idx:
        d = ts.date()
        rs = per_day.get(d, [])
        if rs:
            weights = [r.weight_kg for r in rs if r.weight_kg is not None]
            bfs = [r.body_fat_pct for r in rs if r.body_fat_pct is not None]
            all_controlled = all(
                r.weigh_in_protocol == "controlled_morning" for r in rs
            )
            records.append({
                "weight_kg": float(np.median(weights)) if weights else np.nan,
                "bf_pct": float(np.median(bfs)) if bfs else np.nan,
                "n_weighins": len(rs),
                "weigh_in_protocol_controlled": bool(all_controlled),
            })
        else:
            records.append({
                "weight_kg": np.nan,
                "bf_pct": np.nan,
                "n_weighins": 0,
                "weigh_in_protocol_controlled": False,
            })
    df = pd.DataFrame(records, index=idx)
    df["weigh_in_protocol_controlled"] = df["weigh_in_protocol_controlled"].astype(object)
    return df


def rollup_rhr(
    session: Session, start: datetime.date, end: datetime.date, ffill_days: int = 3
) -> pd.DataFrame:
    """Aggregate resting_heart_rate to one row per day with limited forward-fill.

    Columns: rhr_bpm.

    A measurement on day D fills D and up to ffill_days subsequent days that
    have no reading of their own. Days more than ffill_days beyond the last
    reading return NaN.  A small look-back window before `start` is fetched so
    the first days of the range can benefit from forward-fill too.
    """
    fetch_start = start - datetime.timedelta(days=ffill_days)
    rows = (
        session.query(RestingHeartRate)
        .filter(
            RestingHeartRate.measured_at >= datetime.datetime.combine(fetch_start, datetime.time()),
            RestingHeartRate.measured_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .order_by(RestingHeartRate.measured_at)
        .all()
    )
    # Most-recent reading per calendar date (last write wins).
    by_date: dict[datetime.date, int] = {}
    for r in rows:
        by_date[r.measured_at.date()] = r.bpm

    idx = _date_index(start, end)
    records = []
    for ts in idx:
        d = ts.date()
        value = np.nan
        for back in range(ffill_days + 1):
            cand = d - datetime.timedelta(days=back)
            if cand in by_date:
                value = float(by_date[cand])
                break
        records.append({"rhr_bpm": value})
    return pd.DataFrame(records, index=idx)


def rollup_sleep(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    """Aggregate sleep_sessions to one row per day (previous-night convention).

    Columns: sleep_total_h_prev_night.

    A sleep session ending before noon on day D is counted as the previous
    night's sleep for day D (i.e. it appears in row D).  Sessions ending at
    noon or later (naps / unusual daytime sleep) are excluded.  Duration is
    taken directly from duration_min to match what the sync stores rather than
    recomputing from start/end timestamps.
    """
    fetch_start = start - datetime.timedelta(days=1)
    rows = (
        session.query(SleepSession)
        .filter(
            SleepSession.end_at >= datetime.datetime.combine(fetch_start, datetime.time()),
            SleepSession.end_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time(12, 0)
            ),
        )
        .all()
    )
    per_day: dict[datetime.date, float] = {}
    for r in rows:
        end_dt = r.end_at
        if end_dt.hour < 12:
            d = end_dt.date()
        else:
            continue  # naps / late-day sleep; not 'prev night'
        per_day[d] = per_day.get(d, 0.0) + r.duration_min / 60.0

    idx = _date_index(start, end)
    records = [
        {"sleep_total_h_prev_night": per_day.get(ts.date(), np.nan)} for ts in idx
    ]
    return pd.DataFrame(records, index=idx)


def rollup_workouts(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    """Aggregate workouts to one row per day.

    Columns: workout_kcal (sum), workout_min (sum).

    Days with no workouts return 0 for both columns (not NaN) so downstream
    math can use the column without masking.
    """
    rows = (
        session.query(Workout)
        .filter(
            Workout.start_at >= datetime.datetime.combine(start, datetime.time()),
            Workout.start_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .all()
    )
    per_day: dict[datetime.date, dict] = {}
    for r in rows:
        cell = per_day.setdefault(r.start_at.date(), {"workout_kcal": 0.0, "workout_min": 0})
        cell["workout_kcal"] += r.calories_kcal or 0
        cell["workout_min"] += r.duration_min or 0

    idx = _date_index(start, end)
    records = [
        per_day.get(ts.date(), {"workout_kcal": 0.0, "workout_min": 0}) for ts in idx
    ]
    return pd.DataFrame(records, index=idx)


def first_food_log_date(session: Session) -> datetime.date | None:
    """Return the date of the earliest FoodEntry in the database.

    Used by notebooks to scope the rollup window to actual logging history
    rather than pulling in N days of pre-logging emptiness. Returns None if
    no food entries exist yet.
    """
    ts = session.query(func.min(FoodEntry.logged_at)).scalar()
    return ts.date() if ts else None


def build_daily_rollup(
    session: Session,
    start: datetime.date,
    end: datetime.date,
    weight_kg_fallback: float,
    age: int,
    sex: str,
    keytel_baseline_method: baseline.BaselineMethod = "resting_states_p10",
) -> pd.DataFrame:
    """Build the canonical daily-rollup DataFrame for body_sim.

    Args:
        session: SQLAlchemy session against the foodlog DB
        start, end: inclusive date range
        weight_kg_fallback: weight to use for Keytel on days before any observed weigh-in
        age, sex: user profile
        keytel_baseline_method: how to estimate the per-day awake-resting HR
            floor that gets subtracted from Keytel before integrating. Default
            ``"resting_states_p10"`` — the empirical winner from foodlog-w76,
            takes the 10th-percentile bpm across HR windows where the user has
            zero steps, is awake, and is not in a workout. ``"naive"`` reverts
            to the pre-fix unsubtracted integral.

    Returns:
        DataFrame indexed by date, one row per day in [start, end].
    """
    food = rollup_food(session, start, end)
    bc = rollup_body_comp(session, start, end)
    rhr = rollup_rhr(session, start, end)
    sleep = rollup_sleep(session, start, end)
    workouts = rollup_workouts(session, start, end)

    # Reference weight per day: most recent observed weight up to and including
    # that day, or the *first* observed weight for the leading gap before any
    # weigh-in exists, or the literal fallback if there are no observations at
    # all. The bfill prevents a static 80.0 kg fallback from biasing Keytel on
    # days where we have HR data but no weigh-in yet.
    weight_series = bc["weight_kg"].ffill().bfill().fillna(weight_kg_fallback)

    # Per-day baseline HR (None series for "naive" — fast path; otherwise compute
    # the baseline per day and forward-fill across days the method can't cover
    # (weekends for desk methods; nights without recorded sleep for sleep method).
    baseline_series = _build_baseline_series(
        session, weight_series.index, keytel_baseline_method
    )

    activity = rollup_activity_with_per_day_weight(
        session, start, end, weight_series, age, sex, baseline_series
    )

    df = pd.concat([food, activity, bc, rhr, sleep, workouts], axis=1)
    df["reference_weight_kg"] = weight_series
    return df


def _build_baseline_series(
    session: Session,
    idx: pd.DatetimeIndex,
    method: baseline.BaselineMethod,
) -> pd.Series:
    """Per-day baseline HR with forward-fill across uncovered days.

    Returns an all-NaN series for method=="naive" so callers fall through to
    the unsubtracted integral.
    """
    if method == "naive":
        return pd.Series(np.nan, index=idx, dtype=float)
    raw = pd.Series(
        [baseline.baseline_for_day(session, ts.date(), method) for ts in idx],
        index=idx,
        dtype="float64",
    )
    # Forward-fill across weekends / sleep-less days; back-fill the leading
    # gap if the series starts on an uncovered day.
    return raw.ffill().bfill()


def rollup_activity_with_per_day_weight(
    session: Session,
    start: datetime.date,
    end: datetime.date,
    weight_series: pd.Series,
    age: int,
    sex: str,
    baseline_series: pd.Series | None = None,
) -> pd.DataFrame:
    """Variant of rollup_activity that uses a per-day weight Series for Keytel.

    Calls rollup_activity day-by-day so the Keytel integral matches the
    reference weight on each day. Slightly wasteful in queries but trivial for
    Phase 1 data volumes.
    """
    frames = []
    for ts, weight in weight_series.items():
        d = ts.date()
        baseline_hr: float | None = None
        if baseline_series is not None:
            v = baseline_series.get(ts)
            if v is not None and pd.notna(v):
                baseline_hr = float(v)
        sub = rollup_activity(
            session, start=d, end=d, weight_kg=float(weight),
            age=age, sex=sex, baseline_hr=baseline_hr,
        )
        frames.append(sub)
    return pd.concat(frames)
