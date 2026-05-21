"""Personal awake-resting HR baselines for the Keytel structural fix.

Three candidate baselines, evaluated empirically against weigh-in residuals:

- ``sleep``: mean HR during sleep windows touching the day. Low — sleep HR
  reflects parasympathetic dominance, not awake-sedentary metabolism. Will
  under-subtract.
- ``avg_desk``: mean HR during the 10:00–11:00 and 14:00–15:00 windows.
  This is the target Mifflin RMR is calibrated to (awake sitting quietly).
- ``min_desk``: minimum HR during the same windows. Captures the floor of
  awake-resting HR; will subtract too little compared to the typical state.

Each function takes a SQLAlchemy session + a `datetime.date` and returns
the per-day baseline bpm, or `None` if the underlying data is missing
(e.g. no sleep session that day; no desk-window HR rows).
"""

from __future__ import annotations

import datetime
import statistics
from typing import Literal

from sqlalchemy import and_

from foodlog.db.models import (
    IntervalActivity,
    IntervalHeartRate,
    SleepSession,
    Workout,
)


BaselineMethod = Literal[
    "naive",
    "sleep",
    "avg_desk",
    "min_desk",
    "resting_states",            # median of eligible windows
    "resting_states_p10",        # P10 of eligible windows (robust floor)
    "evening_avg",               # mean HR during 18:00-22:00 (any day)
    "evening_min",               # min HR during 18:00-22:00
    "evening_resting_p10",       # P10 of eligible windows ∩ 18:00-22:00
]


# Office desk windows. Weekdays only — weekends violate the "at desk" assumption.
# Hours are local-time hours; IntervalHeartRate.start_at is stored as naive local
# datetime per foodlog convention.
DESK_HOURS: tuple[tuple[int, int], ...] = ((10, 11), (14, 15))

# Evening couch hours — 18:00-22:00. Every day (weekday or not). Post-work
# parasympathetic recovery, no caffeine, mostly sedentary on most days.
EVENING_HOURS: tuple[tuple[int, int], ...] = ((18, 22),)


def _is_weekday(day: datetime.date) -> bool:
    return day.weekday() < 5


def _hr_rows_in_range(
    session, start: datetime.datetime, end: datetime.datetime
) -> list[IntervalHeartRate]:
    """Pull HR rows whose start_at is in [start, end)."""
    return (
        session.query(IntervalHeartRate)
        .filter(
            and_(
                IntervalHeartRate.start_at >= start,
                IntervalHeartRate.start_at < end,
            )
        )
        .all()
    )


def sleep_baseline(session, day: datetime.date) -> float | None:
    """Mean ``bpm_avg`` during sleep sessions that overlap ``day``.

    Includes the prior-night sleep that ends on this date and any naps. Returns
    None when there is no sleep session or no HR data covering the sleep period.
    """
    day_start = datetime.datetime.combine(day, datetime.time())
    day_end = day_start + datetime.timedelta(days=1)
    sleeps = (
        session.query(SleepSession)
        .filter(
            and_(
                SleepSession.start_at < day_end,
                SleepSession.end_at >= day_start,
            )
        )
        .all()
    )
    if not sleeps:
        return None

    bpms: list[float] = []
    for s in sleeps:
        # Clip the sleep window to the day's bounds so cross-midnight sleeps
        # contribute the part that falls on `day`.
        s_start = max(s.start_at, day_start)
        s_end = min(s.end_at, day_end)
        if s_end <= s_start:
            continue
        hr_rows = _hr_rows_in_range(session, s_start, s_end)
        bpms.extend(r.bpm_avg for r in hr_rows if r.bpm_avg is not None)
    if not bpms:
        return None
    return float(statistics.mean(bpms))


def _window_bpms(
    session,
    day: datetime.date,
    hours: tuple[tuple[int, int], ...],
    weekday_only: bool,
) -> list[float]:
    """Collect bpm_avg values for HR rows whose start_at falls in any hour
    window in ``hours`` on ``day``. Empty list when weekday_only and weekend.
    """
    if weekday_only and not _is_weekday(day):
        return []
    bpms: list[float] = []
    for h_start, h_end in hours:
        win_start = datetime.datetime.combine(day, datetime.time(h_start, 0))
        win_end = datetime.datetime.combine(day, datetime.time(h_end, 0))
        rows = _hr_rows_in_range(session, win_start, win_end)
        bpms.extend(r.bpm_avg for r in rows if r.bpm_avg is not None)
    return bpms


def _desk_window_bpms(session, day: datetime.date) -> list[float]:
    return _window_bpms(session, day, DESK_HOURS, weekday_only=True)


def avg_desk_baseline(session, day: datetime.date) -> float | None:
    """Mean bpm_avg across desk-hour windows. None if no data (or weekend)."""
    bpms = _desk_window_bpms(session, day)
    if not bpms:
        return None
    return float(statistics.mean(bpms))


def min_desk_baseline(session, day: datetime.date) -> float | None:
    """Minimum bpm_avg across desk-hour windows. None if no data (or weekend)."""
    bpms = _desk_window_bpms(session, day)
    if not bpms:
        return None
    return float(min(bpms))


def avg_evening_baseline(session, day: datetime.date) -> float | None:
    """Mean bpm_avg during 18:00-22:00. None if no data."""
    bpms = _window_bpms(session, day, EVENING_HOURS, weekday_only=False)
    if not bpms:
        return None
    return float(statistics.mean(bpms))


def min_evening_baseline(session, day: datetime.date) -> float | None:
    """Min bpm_avg during 18:00-22:00. None if no data."""
    bpms = _window_bpms(session, day, EVENING_HOURS, weekday_only=False)
    if not bpms:
        return None
    return float(min(bpms))


def _floor_15min(t: datetime.datetime) -> datetime.datetime:
    """Bucket a timestamp to its containing 15-min wallclock boundary."""
    minute = (t.minute // 15) * 15
    return t.replace(minute=minute, second=0, microsecond=0)


def resting_states_baseline(
    session,
    day: datetime.date,
    quantile: float = 0.5,
    hour_window: tuple[tuple[int, int], ...] | None = None,
) -> float | None:
    """Quantile of bpm across HR windows where the user is *physiologically* resting.

    Eligibility per 15-min window:
      - steps in window == 0 (any nonzero stepping disqualifies)
      - window does NOT overlap a SleepSession (sleep ≠ awake-resting; Mifflin
        is calibrated to awake-resting metabolism)
      - window does NOT overlap a recorded Workout
      - if ``hour_window`` is supplied, window start_at must fall within one of
        the (start_hour, end_hour) ranges (e.g. ``((18, 22),)`` for evening)

    The HR distribution across eligible windows is the user's *awake-sedentary*
    HR distribution. Choice of quantile:
      - 0.5 (median): robust central tendency; biased high by lots of
        "desk-doing-work" hours that include mild cognitive demand and posture
        engagement above true rest.
      - 0.1 (P10): the awake-resting *floor* using the full day's data; more
        robust than a single-point minimum but lower than the median.

    Returns None when no eligible windows exist on the day.
    """
    day_start = datetime.datetime.combine(day, datetime.time())
    day_end = day_start + datetime.timedelta(days=1)

    hr_rows = _hr_rows_in_range(session, day_start, day_end)
    if not hr_rows:
        return None

    # Sum steps per 15-min bucket (some buckets may have zero IntervalActivity
    # rows — Google Health omits zero-step windows, so absence ≡ 0 steps).
    ia_rows = (
        session.query(IntervalActivity)
        .filter(
            and_(
                IntervalActivity.start_at >= day_start,
                IntervalActivity.start_at < day_end,
            )
        )
        .all()
    )
    steps_by_bucket: dict[datetime.datetime, int] = {}
    for r in ia_rows:
        b = _floor_15min(r.start_at)
        steps_by_bucket[b] = steps_by_bucket.get(b, 0) + (r.steps or 0)

    sleeps = (
        session.query(SleepSession)
        .filter(
            and_(SleepSession.start_at < day_end, SleepSession.end_at >= day_start)
        )
        .all()
    )
    workouts = (
        session.query(Workout)
        .filter(and_(Workout.start_at < day_end, Workout.end_at >= day_start))
        .all()
    )

    def _in_hour_window(t: datetime.datetime) -> bool:
        if hour_window is None:
            return True
        return any(h_start <= t.hour < h_end for h_start, h_end in hour_window)

    bpms: list[float] = []
    for r in hr_rows:
        t = r.start_at
        if r.bpm_avg is None:
            continue
        if not _in_hour_window(t):
            continue
        if steps_by_bucket.get(_floor_15min(t), 0) > 0:
            continue
        if any(s.start_at <= t < s.end_at for s in sleeps):
            continue
        if any(w.start_at <= t < w.end_at for w in workouts):
            continue
        bpms.append(float(r.bpm_avg))

    if not bpms:
        return None
    return _quantile(bpms, quantile)


def _quantile(values: list[float], q: float) -> float:
    """Linear-interpolated quantile (matches numpy default). q in [0, 1]."""
    if not values:
        raise ValueError("quantile of empty sequence")
    s = sorted(values)
    if q <= 0:
        return float(s[0])
    if q >= 1:
        return float(s[-1])
    pos = q * (len(s) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 < len(s):
        return float(s[lo] * (1 - frac) + s[lo + 1] * frac)
    return float(s[lo])


def baseline_for_day(
    session, day: datetime.date, method: BaselineMethod
) -> float | None:
    """Dispatch to one of the baseline methods.

    Returns None for the ``naive`` method (no baseline — caller should fall
    back to the unsubtracted ``keytel.daily_integral``).
    """
    if method == "naive":
        return None
    if method == "sleep":
        return sleep_baseline(session, day)
    if method == "avg_desk":
        return avg_desk_baseline(session, day)
    if method == "min_desk":
        return min_desk_baseline(session, day)
    if method == "resting_states":
        return resting_states_baseline(session, day, quantile=0.5)
    if method == "resting_states_p10":
        return resting_states_baseline(session, day, quantile=0.10)
    if method == "evening_avg":
        return avg_evening_baseline(session, day)
    if method == "evening_min":
        return min_evening_baseline(session, day)
    if method == "evening_resting_p10":
        return resting_states_baseline(
            session, day, quantile=0.10, hour_window=EVENING_HOURS
        )
    raise ValueError(f"unknown baseline method: {method!r}")
