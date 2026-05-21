import datetime

import numpy as np
import pytest

from body_sim import pipeline
from foodlog.db.models import BodyComposition, RestingHeartRate, SleepSession, Workout


def test_body_comp_rollup_empty(session):
    df = pipeline.rollup_body_comp(
        session, start=datetime.date(2026, 5, 1), end=datetime.date(2026, 5, 2)
    )
    assert df["weight_kg"].isna().all()
    assert df["bf_pct"].isna().all()
    assert (df["n_weighins"] == 0).all()


def test_body_comp_rollup_single_reading(session):
    d = datetime.date(2026, 5, 1)
    session.add(BodyComposition(
        external_id="bc-1",
        measured_at=datetime.datetime(2026, 5, 1, 7, 30),
        source="withings",
        weight_kg=80.5,
        body_fat_pct=22.0,
    ))
    session.commit()
    df = pipeline.rollup_body_comp(session, start=d, end=d)
    row = df.iloc[0]
    assert row["weight_kg"] == pytest.approx(80.5)
    assert row["bf_pct"] == pytest.approx(22.0)
    assert row["n_weighins"] == 1


def test_body_comp_rollup_median_of_multiple(session):
    d = datetime.date(2026, 5, 1)
    for i, (w, bf) in enumerate([(80.0, 22.0), (80.5, 22.5), (81.0, 23.0)]):
        session.add(BodyComposition(
            external_id=f"bc-{i}",
            measured_at=datetime.datetime(2026, 5, 1, 7 + i, 0),
            source="withings",
            weight_kg=w,
            body_fat_pct=bf,
        ))
    session.commit()
    df = pipeline.rollup_body_comp(session, start=d, end=d)
    row = df.iloc[0]
    assert row["weight_kg"] == pytest.approx(80.5)  # median
    assert row["bf_pct"] == pytest.approx(22.5)
    assert row["n_weighins"] == 3


def test_body_comp_rollup_skips_excluded_external_ids(session):
    """Rows whose external_id is in EXCLUDED_BODY_COMP_IDS don't reach the rollup."""
    d = datetime.date(2026, 5, 1)
    excluded_id = next(iter(pipeline.EXCLUDED_BODY_COMP_IDS))
    session.add(BodyComposition(
        external_id=excluded_id,
        measured_at=datetime.datetime(2026, 5, 1, 8, 0),
        source="withings",
        weight_kg=99.9,
        body_fat_pct=33.3,
    ))
    session.add(BodyComposition(
        external_id="not-excluded",
        measured_at=datetime.datetime(2026, 5, 1, 9, 0),
        source="withings",
        weight_kg=80.0,
        body_fat_pct=22.0,
    ))
    session.commit()
    df = pipeline.rollup_body_comp(session, start=d, end=d)
    row = df.iloc[0]
    assert row["weight_kg"] == pytest.approx(80.0)
    assert row["bf_pct"] == pytest.approx(22.0)
    assert row["n_weighins"] == 1


def test_rhr_rollup_forward_fills_three_days(session):
    # RHR on day 1, missing days 2-4. Days 2-3-4 forward-fill; day 5 NaN.
    session.add(RestingHeartRate(
        external_id="rhr-1",
        measured_at=datetime.datetime(2026, 5, 1, 0, 0),
        source="fitbit",
        bpm=58,
    ))
    session.commit()
    df = pipeline.rollup_rhr(
        session, start=datetime.date(2026, 5, 1), end=datetime.date(2026, 5, 6)
    )
    assert df.iloc[0]["rhr_bpm"] == 58
    assert df.iloc[1]["rhr_bpm"] == 58  # ffill day 1
    assert df.iloc[2]["rhr_bpm"] == 58  # ffill day 2
    assert df.iloc[3]["rhr_bpm"] == 58  # ffill day 3
    assert np.isnan(df.iloc[4]["rhr_bpm"])  # past 3-day ffill, NaN
    assert np.isnan(df.iloc[5]["rhr_bpm"])


def test_sleep_rollup_prev_night(session):
    # Sleep ending early morning of 2026-05-02 → assigned to 2026-05-02 row
    session.add(SleepSession(
        external_id="sleep-1",
        start_at=datetime.datetime(2026, 5, 1, 23, 30),
        end_at=datetime.datetime(2026, 5, 2, 7, 0),
        duration_min=450,
        source="fitbit",
    ))
    session.commit()
    df = pipeline.rollup_sleep(
        session, start=datetime.date(2026, 5, 1), end=datetime.date(2026, 5, 2)
    )
    assert np.isnan(df.iloc[0]["sleep_total_h_prev_night"])  # no row for day 1
    assert df.iloc[1]["sleep_total_h_prev_night"] == pytest.approx(7.5)


def test_workouts_rollup_zero_when_none(session):
    df = pipeline.rollup_workouts(
        session, start=datetime.date(2026, 5, 1), end=datetime.date(2026, 5, 1)
    )
    assert df.iloc[0]["workout_kcal"] == 0
    assert df.iloc[0]["workout_min"] == 0


def test_workouts_rollup_aggregates_by_start_date(session):
    d = datetime.date(2026, 5, 1)
    session.add(Workout(
        external_id="w-1",
        start_at=datetime.datetime(2026, 5, 1, 6, 0),
        end_at=datetime.datetime(2026, 5, 1, 7, 0),
        activity_type="run",
        duration_min=60,
        calories_kcal=500.0,
        source="fitbit",
    ))
    session.add(Workout(
        external_id="w-2",
        start_at=datetime.datetime(2026, 5, 1, 18, 0),
        end_at=datetime.datetime(2026, 5, 1, 18, 30),
        activity_type="weights",
        duration_min=30,
        calories_kcal=150.0,
        source="manual",
    ))
    session.commit()
    df = pipeline.rollup_workouts(session, start=d, end=d)
    assert df.iloc[0]["workout_kcal"] == pytest.approx(650.0)
    assert df.iloc[0]["workout_min"] == 90


def test_body_composition_has_weigh_in_protocol_column():
    """Schema regression: the BodyComposition model must expose
    weigh_in_protocol so sync-time tagging + backfill have a place to write."""
    from foodlog.db.models import BodyComposition
    assert hasattr(BodyComposition, "weigh_in_protocol"), (
        "BodyComposition.weigh_in_protocol missing — schema migration "
        "(foodlog-hg8) not applied"
    )


def test_rollup_body_comp_emits_protocol_controlled_flag(session):
    """A day with all weigh-ins flagged controlled_morning gets
    weigh_in_protocol_controlled=True; a day with any uncontrolled weigh-in
    gets False; a day with no weigh-ins gets False."""
    session.add(BodyComposition(
        external_id="a", measured_at=datetime.datetime(2026, 5, 22, 9, 0),
        weight_kg=82.0, body_fat_pct=21.0, source="test",
        weigh_in_protocol="controlled_morning",
    ))
    session.add(BodyComposition(
        external_id="b", measured_at=datetime.datetime(2026, 5, 23, 9, 0),
        weight_kg=82.5, body_fat_pct=21.1, source="test",
        weigh_in_protocol="controlled_morning",
    ))
    session.add(BodyComposition(
        external_id="c", measured_at=datetime.datetime(2026, 5, 23, 19, 0),
        weight_kg=83.0, body_fat_pct=21.2, source="test",
        weigh_in_protocol="uncontrolled",
    ))
    session.commit()

    out = pipeline.rollup_body_comp(
        session, datetime.date(2026, 5, 22), datetime.date(2026, 5, 24)
    )
    assert out.loc[datetime.datetime(2026, 5, 22), "weigh_in_protocol_controlled"] is True
    assert out.loc[datetime.datetime(2026, 5, 23), "weigh_in_protocol_controlled"] is False
    assert out.loc[datetime.datetime(2026, 5, 24), "weigh_in_protocol_controlled"] is False
