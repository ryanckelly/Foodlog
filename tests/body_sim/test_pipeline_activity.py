import datetime

import numpy as np
import pandas as pd
import pytest

from body_sim import pipeline
from foodlog.db.models import DailyActivity, IntervalAzm, IntervalHeartRate


def _add_daily_activity(db, d: datetime.date, steps: int, active_kcal: float):
    db.add(
        DailyActivity(
            date=d,
            steps=steps,
            active_calories_kcal=active_kcal,
            source="fitbit",
            external_id=f"da-{d}",
        )
    )


def _add_hr_interval(db, dt: datetime.datetime, bpm: int):
    db.add(
        IntervalHeartRate(
            start_at=dt,
            bpm_avg=bpm,
            bpm_min=bpm - 5,
            bpm_max=bpm + 5,
            source="fitbit",
        )
    )


def _add_azm(db, dt: datetime.datetime, fat_burn: int = 0, cardio: int = 0, peak: int = 0):
    db.add(
        IntervalAzm(
            start_at=dt,
            fat_burn_min=fat_burn,
            cardio_min=cardio,
            peak_min=peak,
            source="fitbit",
        )
    )


def test_activity_rollup_empty(session):
    df = pipeline.rollup_activity(
        session,
        start=datetime.date(2026, 5, 1),
        end=datetime.date(2026, 5, 2),
        weight_kg=80.0,
        age=40,
        sex="male",
    )
    assert len(df) == 2
    assert df["steps"].isna().all()
    assert (df["vigorous_min"] == 0).all()
    assert (df["hr_coverage_pct"] == 0.0).all()


def test_activity_rollup_daily_only(session):
    d = datetime.date(2026, 5, 1)
    _add_daily_activity(session, d, steps=10000, active_kcal=400.0)
    session.commit()
    df = pipeline.rollup_activity(
        session, start=d, end=d, weight_kg=80.0, age=40, sex="male"
    )
    row = df.iloc[0]
    assert row["steps"] == 10000
    assert row["active_kcal_fitbit"] == pytest.approx(400.0)


def test_activity_rollup_with_full_hr_coverage(session):
    d = datetime.date(2026, 5, 1)
    _add_daily_activity(session, d, steps=8000, active_kcal=300.0)
    # 1440 minutes of HR at 80 bpm
    for m in range(1440):
        dt = datetime.datetime.combine(d, datetime.time()) + datetime.timedelta(minutes=m)
        _add_hr_interval(session, dt, bpm=80)
    session.commit()
    df = pipeline.rollup_activity(
        session, start=d, end=d, weight_kg=80.0, age=40, sex="male"
    )
    row = df.iloc[0]
    assert row["hr_coverage_pct"] == pytest.approx(100.0, abs=0.1)
    assert row["ee_hr_keytel_kcal"] > 1000  # plausible 24h expenditure at 80 bpm avg


def test_activity_rollup_aggregates_azm(session):
    d = datetime.date(2026, 5, 1)
    _add_azm(session, datetime.datetime(2026, 5, 1, 8, 0), fat_burn=10)
    _add_azm(session, datetime.datetime(2026, 5, 1, 10, 0), cardio=15)
    _add_azm(session, datetime.datetime(2026, 5, 1, 18, 0), peak=5, cardio=5)
    session.commit()
    df = pipeline.rollup_activity(
        session, start=d, end=d, weight_kg=80.0, age=40, sex="male"
    )
    row = df.iloc[0]
    assert row["cardio_min"] == 20
    assert row["vigorous_min"] == 5  # peak only


def test_activity_rollup_partial_hr_coverage(session):
    d = datetime.date(2026, 5, 1)
    # Only 12 hours of HR data
    for m in range(720):
        dt = datetime.datetime.combine(d, datetime.time()) + datetime.timedelta(minutes=m)
        _add_hr_interval(session, dt, bpm=80)
    session.commit()
    df = pipeline.rollup_activity(
        session, start=d, end=d, weight_kg=80.0, age=40, sex="male"
    )
    row = df.iloc[0]
    assert row["hr_coverage_pct"] == pytest.approx(50.0, abs=0.5)
