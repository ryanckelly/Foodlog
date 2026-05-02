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


@pytest.mark.asyncio
async def test_sync_interval_heart_rate_upserts_idempotently(db_session, monkeypatch):
    from foodlog.clients.google_health import HrIntervalRow
    from foodlog.db.models import IntervalHeartRate
    from foodlog.services.health_sync import HealthSyncService

    rows = [
        HrIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
            bpm_avg=110, bpm_min=88, bpm_max=140, source="FITBIT",
        ),
        HrIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 15, 0),
            bpm_avg=115, bpm_min=92, bpm_max=145, source="FITBIT",
        ),
    ]

    class StubClient:
        async def list_hr_intervals(self, since, until=None):
            for r in rows:
                yield r

    sync = HealthSyncService(db_session, StubClient())
    n1 = await sync._sync_interval_heart_rate()
    n2 = await sync._sync_interval_heart_rate()  # second run: still 2, no duplicates
    assert n1 == 2
    assert n2 == 2
    stored = db_session.query(IntervalHeartRate).all()
    assert len(stored) == 2
    assert stored[0].bpm_avg == 110


@pytest.mark.asyncio
async def test_sync_interval_activity_upserts_with_nullable_columns(db_session):
    from foodlog.clients.google_health import ActivityIntervalRow
    from foodlog.db.models import IntervalActivity
    from foodlog.services.health_sync import HealthSyncService

    rows = [
        ActivityIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
            steps=649, distance_m=420.268, floors=None, source="FITBIT",
        ),
        ActivityIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 15, 0),
            steps=792, distance_m=628.5, floors=3, source="FITBIT",
        ),
    ]

    class StubClient:
        async def list_activity_intervals(self, since, until=None):
            for r in rows:
                yield r

    sync = HealthSyncService(db_session, StubClient())
    n = await sync._sync_interval_activity()
    assert n == 2
    stored = db_session.query(IntervalActivity).all()
    assert len(stored) == 2
    assert stored[0].steps == 649
    assert stored[0].floors is None
    assert stored[1].floors == 3


@pytest.mark.asyncio
async def test_sync_interval_azm_upserts(db_session):
    from foodlog.clients.google_health import AzmIntervalRow
    from foodlog.db.models import IntervalAzm
    from foodlog.services.health_sync import HealthSyncService

    rows = [
        AzmIntervalRow(
            start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
            fat_burn_min=8, cardio_min=None, peak_min=None, source="FITBIT",
        ),
    ]

    class StubClient:
        async def list_azm_intervals(self, since, until=None):
            for r in rows:
                yield r

    sync = HealthSyncService(db_session, StubClient())
    n = await sync._sync_interval_azm()
    assert n == 1
    stored = db_session.query(IntervalAzm).first()
    assert stored.fat_burn_min == 8
    assert stored.cardio_min is None


@pytest.mark.asyncio
async def test_sync_all_includes_interval_metrics(db_session):
    from foodlog.clients.google_health import (
        HrIntervalRow, ActivityIntervalRow, AzmIntervalRow,
    )
    from foodlog.services.health_sync import HealthSyncService

    class StubClient:
        async def list_daily_activity(self, since, until=None):
            return; yield  # empty generator
        async def list_body_composition(self, since, until=None):
            return; yield
        async def list_resting_heart_rate(self, since, until=None):
            return; yield
        async def list_sleep_sessions(self, since, until=None):
            return; yield
        async def list_workouts(self, since, until=None):
            return; yield
        async def list_workout_hr_samples(self, workout_id, start_at, end_at):
            return; yield
        async def list_hr_intervals(self, since, until=None):
            yield HrIntervalRow(
                start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
                bpm_avg=110, bpm_min=88, bpm_max=140, source="FITBIT",
            )
        async def list_activity_intervals(self, since, until=None):
            yield ActivityIntervalRow(
                start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
                steps=600, distance_m=400.0, floors=None, source="FITBIT",
            )
        async def list_azm_intervals(self, since, until=None):
            yield AzmIntervalRow(
                start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
                fat_burn_min=5, cardio_min=None, peak_min=None, source="FITBIT",
            )

    sync = HealthSyncService(db_session, StubClient())
    result = await sync.sync_all()
    assert result.ok is True
    assert result.rows_upserted.get("interval_heart_rate") == 1
    assert result.rows_upserted.get("interval_activity") == 1
    assert result.rows_upserted.get("interval_azm") == 1
