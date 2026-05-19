import datetime

import pytest

from body_sim import pipeline
from foodlog.db.models import BodyComposition, DailyActivity, FoodEntry


def test_build_daily_rollup_columns_present(session):
    df = pipeline.build_daily_rollup(
        session,
        start=datetime.date(2026, 5, 1),
        end=datetime.date(2026, 5, 3),
        weight_kg_fallback=80.0,
        age=40,
        sex="male",
    )
    expected_cols = {
        "intake_kcal", "protein_g", "carb_g", "fat_g", "sodium_mg",
        "meal_types_logged", "intake_coverage", "intake_logged",
        "steps", "active_kcal_fitbit", "ee_hr_keytel_kcal",
        "hr_coverage_pct", "vigorous_min", "cardio_min",
        "rhr_bpm",
        "workout_kcal", "workout_min",
        "sleep_total_h_prev_night",
        "weight_kg", "bf_pct", "n_weighins",
    }
    assert expected_cols.issubset(df.columns)
    assert len(df) == 3


def test_build_daily_rollup_uses_observed_weight_for_keytel(session):
    # Add a weigh-in on day 1; HR-Keytel on day 2 should use that weight
    d1 = datetime.date(2026, 5, 1)
    d2 = datetime.date(2026, 5, 2)
    session.add(BodyComposition(
        external_id="bc-1",
        measured_at=datetime.datetime(2026, 5, 1, 7, 30),
        source="withings",
        weight_kg=85.0,
        body_fat_pct=22.0,
    ))
    session.commit()

    df = pipeline.build_daily_rollup(
        session, start=d1, end=d2,
        weight_kg_fallback=80.0, age=40, sex="male",
    )
    # We can't directly verify Keytel from here without HR data, but we can
    # confirm a 'reference_weight_kg' column is exposed for diagnostic plotting
    assert "reference_weight_kg" in df.columns
    assert df.loc[df.index[1], "reference_weight_kg"] == pytest.approx(85.0)


def test_build_daily_rollup_fallback_weight_used_when_no_observation(session):
    df = pipeline.build_daily_rollup(
        session,
        start=datetime.date(2026, 5, 1),
        end=datetime.date(2026, 5, 1),
        weight_kg_fallback=80.0, age=40, sex="male",
    )
    assert df.iloc[0]["reference_weight_kg"] == pytest.approx(80.0)
