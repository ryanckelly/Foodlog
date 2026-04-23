import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from foodlog.clients.google_health import (
    BodyCompositionRow,
    DailyActivityRow,
    RestingHeartRateRow,
    SleepSessionRow,
    WorkoutRow,
    HrSampleRow,
)
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    RestingHeartRate,
    SleepSession,
    Workout,
    WorkoutHrSample,
)
from foodlog.services.health_sync import HealthSyncService, SyncResult


async def _collect(items):
    for i in items:
        yield i


@pytest.fixture
def client():
    c = MagicMock()
    c.list_daily_activity = lambda *a, **kw: _collect([
        DailyActivityRow(
            external_id="da-1",
            date=datetime.date(2026, 4, 22),
            steps=8432,
            active_calories_kcal=512.0,
            source="watch",
        )
    ])
    c.list_body_composition = lambda *a, **kw: _collect([
        BodyCompositionRow(
            external_id="bc-1",
            measured_at=datetime.datetime(2026, 4, 22, 7, 0),
            weight_kg=81.4,
            body_fat_pct=None,
            source="renpho",
        )
    ])
    c.list_resting_heart_rate = lambda *a, **kw: _collect([])
    c.list_sleep_sessions = lambda *a, **kw: _collect([])
    c.list_workouts = lambda *a, **kw: _collect([
        WorkoutRow(
            external_id="w-1",
            start_at=datetime.datetime(2026, 4, 22, 17, 0),
            end_at=datetime.datetime(2026, 4, 22, 17, 42),
            activity_type="run",
            duration_min=42,
            calories_kcal=410.0,
            distance_m=6800.0,
            avg_hr=152,
            max_hr=174,
            source="watch",
        )
    ])
    c.list_workout_hr_samples = lambda *a, **kw: _collect([
        HrSampleRow(workout_id="w-1", sample_at=datetime.datetime(2026, 4, 22, 17, 5), bpm=148),
        HrSampleRow(workout_id="w-1", sample_at=datetime.datetime(2026, 4, 22, 17, 6), bpm=149),
    ])
    return c


async def test_sync_inserts_rows(db_session, client):
    svc = HealthSyncService(db_session, client)
    result = await svc.sync_all()
    assert isinstance(result, SyncResult)
    assert db_session.query(DailyActivity).count() == 1
    assert db_session.query(BodyComposition).count() == 1
    assert db_session.query(Workout).count() == 1
    assert db_session.query(WorkoutHrSample).count() == 2


async def test_sync_is_idempotent(db_session, client):
    svc = HealthSyncService(db_session, client)
    await svc.sync_all()
    await svc.sync_all()
    assert db_session.query(DailyActivity).count() == 1
    assert db_session.query(Workout).count() == 1
    assert db_session.query(WorkoutHrSample).count() == 2


async def test_sync_updates_existing_row_on_conflict(db_session, client):
    svc = HealthSyncService(db_session, client)
    await svc.sync_all()
    # pretend the watch re-reports the same day with updated steps
    client.list_daily_activity = lambda *a, **kw: _collect([
        DailyActivityRow(
            external_id="da-1",
            date=datetime.date(2026, 4, 22),
            steps=9000,
            active_calories_kcal=540.0,
            source="watch",
        )
    ])
    await svc.sync_all()
    row = db_session.query(DailyActivity).one()
    assert row.steps == 9000


async def test_cursor_for_workouts_uses_max_start_at(db_session, client):
    from foodlog.services.health_sync import cursor_for
    # empty DB → cursor = 90 days ago
    cursor = cursor_for(db_session, Workout, "start_at", default_days=90)
    expected = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=90)
    assert abs((cursor - expected).total_seconds()) < 5

    db_session.add(Workout(
        external_id="w-0",
        start_at=datetime.datetime(2026, 4, 15, 12, 0),
        end_at=datetime.datetime(2026, 4, 15, 13, 0),
        activity_type="run",
        duration_min=60,
        source="watch",
    ))
    db_session.commit()
    cursor = cursor_for(db_session, Workout, "start_at", default_days=90)
    assert cursor == datetime.datetime(2026, 4, 15, 12, 0)
