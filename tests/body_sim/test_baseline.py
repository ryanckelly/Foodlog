"""Tests for body_sim.baseline — per-day awake-resting HR baselines."""

import datetime

import pytest

from body_sim import baseline
from foodlog.db.models import (
    IntervalActivity,
    IntervalHeartRate,
    SleepSession,
    Workout,
)


def _add_hr(s, day: datetime.date, hour: int, minute: int, bpm: int) -> None:
    s.add(
        IntervalHeartRate(
            start_at=datetime.datetime.combine(day, datetime.time(hour, minute)),
            bpm_avg=bpm,
            bpm_min=bpm,
            bpm_max=bpm,
            source="test",
            fetched_at=datetime.datetime.utcnow(),
        )
    )


def _add_sleep(
    s,
    start: datetime.datetime,
    end: datetime.datetime,
    sleep_type: str = "STAGES",
) -> None:
    s.add(
        SleepSession(
            external_id=f"sleep-{start.isoformat()}",
            start_at=start,
            end_at=end,
            duration_min=int((end - start).total_seconds() // 60),
            source="test",
            sleep_type=sleep_type,
            nap=False,
            stages_status="OK",
            awake_min=0,
            light_min=120,
            deep_min=60,
            rem_min=60,
            restless_min=0,
            asleep_min=240,
            in_period_min=240,
            fetched_at=datetime.datetime.utcnow(),
        )
    )


def test_naive_returns_none(session):
    """Naive method has no baseline — caller should fall back to unsubtracted."""
    day = datetime.date(2026, 5, 6)  # wednesday
    assert baseline.baseline_for_day(session, day, "naive") is None


def test_avg_desk_returns_mean_across_desk_windows(session):
    """avg_desk = mean of HR rows starting in 10:00-11:00 + 14:00-15:00."""
    day = datetime.date(2026, 5, 6)  # wednesday — weekday
    _add_hr(session, day, 10, 0, 60)
    _add_hr(session, day, 10, 30, 70)
    _add_hr(session, day, 14, 0, 80)
    _add_hr(session, day, 14, 45, 90)
    # Outside the desk windows — must be ignored
    _add_hr(session, day, 9, 0, 200)
    _add_hr(session, day, 12, 30, 200)
    _add_hr(session, day, 15, 0, 200)
    session.commit()
    assert baseline.avg_desk_baseline(session, day) == pytest.approx(75.0)


def test_min_desk_returns_lowest_desk_window_hr(session):
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 10, 0, 65)
    _add_hr(session, day, 10, 30, 55)
    _add_hr(session, day, 14, 0, 70)
    session.commit()
    assert baseline.min_desk_baseline(session, day) == 55.0


def test_desk_baselines_return_none_on_weekend(session):
    day = datetime.date(2026, 5, 10)  # sunday
    _add_hr(session, day, 10, 0, 65)
    _add_hr(session, day, 14, 0, 70)
    session.commit()
    assert baseline.avg_desk_baseline(session, day) is None
    assert baseline.min_desk_baseline(session, day) is None


def test_desk_baselines_return_none_when_no_desk_data(session):
    day = datetime.date(2026, 5, 6)
    # HR exists but only outside the desk windows
    _add_hr(session, day, 9, 0, 65)
    _add_hr(session, day, 12, 0, 70)
    session.commit()
    assert baseline.avg_desk_baseline(session, day) is None


def test_sleep_baseline_averages_hr_during_sleep_window(session):
    """Sleep on the night of 2026-05-05 → 2026-05-06. Day = 2026-05-06."""
    day = datetime.date(2026, 5, 6)
    sleep_start = datetime.datetime(2026, 5, 6, 0, 0)  # midnight
    sleep_end = datetime.datetime(2026, 5, 6, 7, 0)
    _add_sleep(session, sleep_start, sleep_end)
    # HR during sleep
    _add_hr(session, day, 1, 0, 50)
    _add_hr(session, day, 3, 0, 52)
    _add_hr(session, day, 5, 0, 54)
    # HR outside sleep — must NOT be included
    _add_hr(session, day, 10, 0, 200)
    session.commit()
    assert baseline.sleep_baseline(session, day) == pytest.approx(52.0)


def test_sleep_baseline_handles_cross_midnight_sleep(session):
    """Sleep starts on day-1 evening and ends on day morning — should still
    contribute the post-midnight portion to the day's sleep baseline."""
    day = datetime.date(2026, 5, 6)
    sleep_start = datetime.datetime(2026, 5, 5, 22, 0)
    sleep_end = datetime.datetime(2026, 5, 6, 6, 0)
    _add_sleep(session, sleep_start, sleep_end)
    _add_hr(session, day, 1, 0, 50)
    _add_hr(session, day, 5, 0, 60)
    session.commit()
    assert baseline.sleep_baseline(session, day) == pytest.approx(55.0)


def test_sleep_baseline_returns_none_with_no_sleep_session(session):
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 1, 0, 50)
    session.commit()
    assert baseline.sleep_baseline(session, day) is None


def test_baseline_for_day_dispatches(session):
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 10, 30, 65)
    session.commit()
    assert baseline.baseline_for_day(session, day, "avg_desk") == 65.0
    with pytest.raises(ValueError):
        baseline.baseline_for_day(session, day, "junk")  # type: ignore[arg-type]


def _add_activity(s, day, hour, minute, steps):
    s.add(
        IntervalActivity(
            start_at=datetime.datetime.combine(day, datetime.time(hour, minute)),
            steps=steps,
            distance_m=0.0,
            floors=0,
            source="test",
            fetched_at=datetime.datetime.utcnow(),
        )
    )


def _add_workout(s, start, end, activity_type="run"):
    s.add(
        Workout(
            external_id=f"wo-{start.isoformat()}",
            start_at=start,
            end_at=end,
            activity_type=activity_type,
            duration_min=int((end - start).total_seconds() // 60),
            calories_kcal=300.0,
            distance_m=5000.0,
            avg_hr=140,
            max_hr=170,
            source="test",
            fetched_at=datetime.datetime.utcnow(),
        )
    )


def test_resting_states_includes_only_zero_step_awake_non_workout_windows(session):
    """Median bpm across HR rows where steps==0, not sleeping, not in a workout."""
    day = datetime.date(2026, 5, 6)
    # Eligible: zero-step windows during awake hours
    _add_hr(session, day, 13, 0, 70)
    _add_hr(session, day, 13, 30, 72)
    _add_hr(session, day, 16, 0, 74)
    # Disqualifying — steps in window
    _add_hr(session, day, 11, 0, 110)
    _add_activity(session, day, 11, 0, 80)
    # Disqualifying — sleep
    _add_hr(session, day, 3, 0, 55)
    _add_sleep(
        session,
        datetime.datetime(2026, 5, 6, 0, 0),
        datetime.datetime(2026, 5, 6, 7, 0),
    )
    # Disqualifying — workout
    _add_hr(session, day, 18, 0, 150)
    _add_workout(
        session,
        datetime.datetime(2026, 5, 6, 17, 30),
        datetime.datetime(2026, 5, 6, 18, 30),
    )
    session.commit()
    # Eligible bpms: 70, 72, 74 → median 72
    assert baseline.resting_states_baseline(session, day) == pytest.approx(72.0)


def test_resting_states_returns_none_with_no_eligible_windows(session):
    """Every HR window has steps; no eligible candidates."""
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 12, 0, 80)
    _add_activity(session, day, 12, 0, 50)
    session.commit()
    assert baseline.resting_states_baseline(session, day) is None


def test_resting_states_treats_missing_activity_row_as_zero_steps(session):
    """Google Health omits zero-step IntervalActivity rows; the eligibility
    check must treat absence as zero, not missing."""
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 13, 0, 65)
    _add_hr(session, day, 13, 30, 67)
    # NO IntervalActivity rows at all → all windows have zero steps
    session.commit()
    assert baseline.resting_states_baseline(session, day) == pytest.approx(66.0)


def test_resting_states_bucket_match_within_15min_window(session):
    """HR at 13:08 + IA at 13:01 should both land in the 13:00 bucket and
    thus pair up — the IA row's steps must disqualify the HR window."""
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 13, 8, 100)
    _add_activity(session, day, 13, 1, 60)
    # Eligible window so we don't return None
    _add_hr(session, day, 15, 0, 70)
    session.commit()
    # Only 15:00 is eligible → median = 70
    assert baseline.resting_states_baseline(session, day) == pytest.approx(70.0)


def test_resting_states_via_dispatcher(session):
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 13, 0, 75)
    session.commit()
    assert (
        baseline.baseline_for_day(session, day, "resting_states")
        == pytest.approx(75.0)
    )


def test_resting_states_p10_returns_low_quantile(session):
    """P10 of 11 evenly-spaced eligible bpms (60..70) ≈ 61.0."""
    day = datetime.date(2026, 5, 6)
    for i, bpm in enumerate(range(60, 71)):
        # 11 eligible windows spread across the afternoon
        _add_hr(session, day, 13, i, bpm)
    session.commit()
    p10 = baseline.baseline_for_day(session, day, "resting_states_p10")
    assert p10 == pytest.approx(61.0, abs=0.1)


def test_quantile_helper_matches_numpy_default():
    import numpy as np
    rng = np.random.default_rng(0)
    values = rng.uniform(50, 100, size=100).tolist()
    for q in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        assert baseline._quantile(values, q) == pytest.approx(
            float(np.quantile(values, q)), abs=1e-9
        )


def test_evening_avg_includes_only_18_to_22(session):
    """evening_avg uses 18:00-21:59 HR rows; outside windows ignored."""
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 18, 0, 60)
    _add_hr(session, day, 19, 30, 70)
    _add_hr(session, day, 21, 45, 80)
    # Outside evening — must be ignored
    _add_hr(session, day, 17, 30, 200)
    _add_hr(session, day, 22, 0, 200)
    session.commit()
    assert baseline.avg_evening_baseline(session, day) == pytest.approx(70.0)


def test_evening_min_returns_lowest(session):
    day = datetime.date(2026, 5, 6)
    _add_hr(session, day, 18, 0, 75)
    _add_hr(session, day, 19, 0, 62)
    _add_hr(session, day, 21, 0, 80)
    session.commit()
    assert baseline.min_evening_baseline(session, day) == 62.0


def test_evening_baselines_work_on_weekend(session):
    """Unlike desk, evening on couch happens on weekends too."""
    day = datetime.date(2026, 5, 10)  # sunday
    _add_hr(session, day, 19, 0, 65)
    _add_hr(session, day, 20, 0, 75)
    session.commit()
    assert baseline.avg_evening_baseline(session, day) == pytest.approx(70.0)
    assert baseline.min_evening_baseline(session, day) == 65.0


def test_evening_resting_p10_intersects_eligibility_with_hour_window(session):
    """evening_resting_p10 = P10 of (zero-step, awake, no-workout) ∩ 18-22."""
    day = datetime.date(2026, 5, 6)
    # 11 evening eligible windows with bpm 60..70 → P10 ≈ 61
    for i, bpm in enumerate(range(60, 71)):
        _add_hr(session, day, 18, i * 5, bpm)  # 18:00, 18:05, ..., 18:50
    # Disqualifying — afternoon zero-step low-bpm reading must be excluded
    _add_hr(session, day, 13, 0, 50)
    session.commit()
    p10 = baseline.baseline_for_day(session, day, "evening_resting_p10")
    # Only the 11 evening windows count; afternoon 50 bpm window is filtered out
    assert p10 == pytest.approx(61.0, abs=0.1)
