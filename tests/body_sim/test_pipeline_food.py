import datetime

import pandas as pd
import pytest

from body_sim import pipeline
from foodlog.db.models import FoodEntry


_sub_counter = [0]


def _make_food_entry(
    db, dt: datetime.datetime, meal_type: str, kcal: float, p=10.0, c=20.0, f=5.0, na=300.0,
    submission_id: str | None = None,
):
    """Add a food entry. Each call defaults to its own submission_id (= a
    distinct eating occasion); pass an explicit submission_id to group several
    items into one occasion (a multi-item meal logged together)."""
    if submission_id is None:
        _sub_counter[0] += 1
        submission_id = f"sub-{_sub_counter[0]}"
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
        submission_id=submission_id,
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
    assert row["intake_coverage"] == pytest.approx(1.0 / 3.0)  # meal-type diversity (display only)
    # Hybrid completeness: 1 occasion, 500 kcal -> below the calorie floor and
    # below the occasions threshold -> incomplete.
    assert row["intake_logged"] is False
    assert row["n_eating_occasions"] == 1


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


def test_completeness_calories_vouch_single_occasion(session):
    """User's rule: one big meal totaling a full day's calories is complete,
    even though it's a single eating occasion and only 1/3 meal-type coverage."""
    d = datetime.date(2026, 5, 1)
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 13, 0), "lunch", 2000.0)
    session.commit()
    row = pipeline.rollup_food(session, start=d, end=d).iloc[0]
    assert row["n_eating_occasions"] == 1
    assert row["intake_coverage"] == pytest.approx(1.0 / 3.0)
    assert row["intake_logged"] is True  # calories vouch


def test_completeness_low_cal_single_occasion_is_incomplete(session):
    """User's rule: one meal at 1000 kcal is probably an incomplete log."""
    d = datetime.date(2026, 5, 1)
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 13, 0), "lunch", 1000.0)
    session.commit()
    row = pipeline.rollup_food(session, start=d, end=d).iloc[0]
    assert row["n_eating_occasions"] == 1
    assert row["intake_logged"] is False


def test_completeness_occasions_vouch_below_calorie_floor(session):
    """Three distinct eating occasions reliably means a tracked day, so a
    genuinely light day (below the calorie floor) still counts as complete."""
    d = datetime.date(2026, 5, 1)
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 8, 0), "breakfast", 400.0)
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 13, 0), "lunch", 450.0)
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 19, 0), "snack", 450.0)
    session.commit()
    row = pipeline.rollup_food(session, start=d, end=d).iloc[0]
    assert row["intake_kcal"] == pytest.approx(1300.0)  # below the 1500 floor
    assert row["n_eating_occasions"] == 3
    assert row["intake_logged"] is True  # occasions vouch


def test_completeness_two_occasions_defers_to_calories(session):
    """Two occasions is ambiguous -> the calorie guardrail decides."""
    d_lo = datetime.date(2026, 5, 1)
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 12, 0), "lunch", 600.0)
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 19, 0), "dinner", 700.0)
    session.commit()
    row_lo = pipeline.rollup_food(session, start=d_lo, end=d_lo).iloc[0]
    assert row_lo["n_eating_occasions"] == 2
    assert row_lo["intake_logged"] is False  # 1300 < floor, only 2 occasions

    d_hi = datetime.date(2026, 5, 2)
    _make_food_entry(session, datetime.datetime(2026, 5, 2, 12, 0), "lunch", 800.0)
    _make_food_entry(session, datetime.datetime(2026, 5, 2, 19, 0), "dinner", 900.0)
    session.commit()
    row_hi = pipeline.rollup_food(session, start=d_hi, end=d_hi).iloc[0]
    assert row_hi["n_eating_occasions"] == 2
    assert row_hi["intake_logged"] is True  # 1700 >= floor


def test_completeness_multi_item_meal_is_one_occasion(session):
    """Several items logged together (shared submission_id) = ONE eating
    occasion, so a single batch-logged meal doesn't fake its way to complete."""
    d = datetime.date(2026, 5, 1)
    for name_kcal in (300.0, 250.0, 200.0):
        _make_food_entry(session, datetime.datetime(2026, 5, 1, 12, 30), "lunch",
                         name_kcal, submission_id="batch-1")
    session.commit()
    row = pipeline.rollup_food(session, start=d, end=d).iloc[0]
    assert row["intake_kcal"] == pytest.approx(750.0)
    assert row["n_eating_occasions"] == 1  # one submission, not three
    assert row["intake_logged"] is False  # 750 < floor, 1 occasion


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
