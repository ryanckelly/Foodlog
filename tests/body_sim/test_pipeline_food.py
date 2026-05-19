import datetime

import pandas as pd
import pytest

from body_sim import pipeline
from foodlog.db.models import FoodEntry


def _make_food_entry(
    db, dt: datetime.datetime, meal_type: str, kcal: float, p=10.0, c=20.0, f=5.0, na=300.0
):
    entry = FoodEntry(
        meal_type=meal_type,
        food_name="test food",
        quantity=1.0,
        unit="serving",
        calories=kcal,
        protein_g=p,
        carbs_g=c,
        fat_g=f,
        sodium_mg=na,
        source="manual",
        raw_input="test",
        logged_at=dt,
    )
    db.add(entry)
    return entry


def test_food_rollup_empty(session):
    df = pipeline.rollup_food(
        session,
        start=datetime.date(2026, 5, 1),
        end=datetime.date(2026, 5, 3),
    )
    # Three rows (one per day in [start, end]), all NaN intake
    assert len(df) == 3
    assert df["intake_kcal"].isna().all()
    assert (df["intake_coverage"] == 0.0).all()


def test_food_rollup_single_meal(session):
    d = datetime.date(2026, 5, 1)
    dt = datetime.datetime(2026, 5, 1, 12, 30)
    _make_food_entry(session, dt, "lunch", 500.0)
    session.commit()
    df = pipeline.rollup_food(session, start=d, end=d)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["intake_kcal"] == pytest.approx(500.0)
    assert row["intake_coverage"] == pytest.approx(1.0 / 3.0)
    assert row["intake_logged"] is False  # below 0.67 threshold


def test_food_rollup_full_coverage(session):
    d = datetime.date(2026, 5, 1)
    for hour, meal in [(8, "breakfast"), (12, "lunch"), (19, "dinner")]:
        dt = datetime.datetime(2026, 5, 1, hour, 0)
        _make_food_entry(session, dt, meal, 600.0)
    session.commit()
    df = pipeline.rollup_food(session, start=d, end=d)
    row = df.iloc[0]
    assert row["intake_kcal"] == pytest.approx(1800.0)
    assert row["intake_coverage"] == pytest.approx(1.0)
    assert row["intake_logged"] is True


def test_food_rollup_snacks_ignored_for_coverage(session):
    d = datetime.date(2026, 5, 1)
    # Lunch + 5 snacks: coverage should still be 1/3, not 2/3
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 12, 0), "lunch", 500.0)
    for h in range(13, 18):
        _make_food_entry(session, datetime.datetime(2026, 5, 1, h, 0), "snack", 100.0)
    session.commit()
    df = pipeline.rollup_food(session, start=d, end=d)
    row = df.iloc[0]
    assert row["intake_coverage"] == pytest.approx(1.0 / 3.0)


def test_food_rollup_aggregates_macros(session):
    d = datetime.date(2026, 5, 1)
    _make_food_entry(
        session, datetime.datetime(2026, 5, 1, 8, 0), "breakfast", 500.0,
        p=30, c=50, f=15, na=400,
    )
    _make_food_entry(
        session, datetime.datetime(2026, 5, 1, 12, 0), "lunch", 700.0,
        p=40, c=80, f=20, na=600,
    )
    session.commit()
    df = pipeline.rollup_food(session, start=d, end=d)
    row = df.iloc[0]
    assert row["protein_g"] == pytest.approx(70.0)
    assert row["carb_g"] == pytest.approx(130.0)
    assert row["fat_g"] == pytest.approx(35.0)
    assert row["sodium_mg"] == pytest.approx(1000.0)
