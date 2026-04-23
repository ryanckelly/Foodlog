"""Orchestrate Google Health → FoodLog DB sync.

Per-table cursor derived from data timestamps (robust against clock skew).
All writes use upsert-on-conflict keyed by ``external_id`` for idempotency.
Runs synchronously inside a dashboard request handler.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from foodlog.clients.google_health import GoogleHealthClient, RateLimited, GoogleHealthError
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    RestingHeartRate,
    SleepSession,
    Workout,
    WorkoutHrSample,
)

DEFAULT_BACKFILL_DAYS = 90


@dataclass(slots=True)
class SyncResult:
    ok: bool = True
    rate_limited: bool = False
    server_error: bool = False
    rows_upserted: dict[str, int] = field(default_factory=dict)


def cursor_for(
    db: Session,
    model: Any,
    timestamp_attr: str,
    default_days: int,
) -> datetime.datetime:
    """Return max(timestamp_attr) or now-default_days if the table is empty."""
    col = getattr(model, timestamp_attr)
    row = db.execute(select(func.max(col))).scalar_one_or_none()
    if row is not None:
        return row
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=default_days)


class HealthSyncService:
    def __init__(self, db: Session, client: GoogleHealthClient):
        self._db = db
        self._client = client

    async def sync_all(self) -> SyncResult:
        result = SyncResult()
        try:
            result.rows_upserted["daily_activity"] = await self._sync_daily_activity()
            result.rows_upserted["body_composition"] = await self._sync_body_composition()
            result.rows_upserted["resting_heart_rate"] = await self._sync_resting_hr()
            result.rows_upserted["sleep_sessions"] = await self._sync_sleep()
            wcount, hrcount = await self._sync_workouts_with_hr()
            result.rows_upserted["workouts"] = wcount
            result.rows_upserted["workout_hr_samples"] = hrcount
        except RateLimited:
            result.ok = False
            result.rate_limited = True
        except GoogleHealthError:
            result.ok = False
            result.server_error = True
        return result

    # ---------- per-table sync methods ----------

    async def _sync_daily_activity(self) -> int:
        # Always re-fetch today and yesterday; daily totals can change late.
        today = datetime.date.today()
        since = datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time.min)
        count = 0
        async for row in self._client.list_daily_activity(since=since):
            stmt = sqlite_insert(DailyActivity).values(
                date=row.date,
                steps=row.steps,
                active_calories_kcal=row.active_calories_kcal,
                source=row.source,
                external_id=row.external_id,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["date"],
                set_=dict(
                    steps=row.steps,
                    active_calories_kcal=row.active_calories_kcal,
                    source=row.source,
                    external_id=row.external_id,
                ),
            )
            self._db.execute(stmt)
            count += 1
        self._db.commit()
        return count

    async def _sync_body_composition(self) -> int:
        since = cursor_for(self._db, BodyComposition, "measured_at", DEFAULT_BACKFILL_DAYS)
        count = 0
        async for row in self._client.list_body_composition(since=since):
            stmt = sqlite_insert(BodyComposition).values(
                external_id=row.external_id,
                measured_at=row.measured_at,
                weight_kg=row.weight_kg,
                body_fat_pct=row.body_fat_pct,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(
                    measured_at=row.measured_at,
                    weight_kg=row.weight_kg,
                    body_fat_pct=row.body_fat_pct,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
            count += 1
        self._db.commit()
        return count

    async def _sync_resting_hr(self) -> int:
        since = cursor_for(self._db, RestingHeartRate, "measured_at", DEFAULT_BACKFILL_DAYS)
        count = 0
        async for row in self._client.list_resting_heart_rate(since=since):
            stmt = sqlite_insert(RestingHeartRate).values(
                external_id=row.external_id,
                measured_at=row.measured_at,
                source=row.source,
                bpm=row.bpm,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(measured_at=row.measured_at, bpm=row.bpm, source=row.source),
            )
            self._db.execute(stmt)
            count += 1
        self._db.commit()
        return count

    async def _sync_sleep(self) -> int:
        since = cursor_for(self._db, SleepSession, "start_at", DEFAULT_BACKFILL_DAYS)
        count = 0
        async for row in self._client.list_sleep_sessions(since=since):
            stmt = sqlite_insert(SleepSession).values(
                external_id=row.external_id,
                start_at=row.start_at,
                end_at=row.end_at,
                duration_min=row.duration_min,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(
                    start_at=row.start_at,
                    end_at=row.end_at,
                    duration_min=row.duration_min,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
            count += 1
        self._db.commit()
        return count

    async def _sync_workouts_with_hr(self) -> tuple[int, int]:
        since = cursor_for(self._db, Workout, "start_at", DEFAULT_BACKFILL_DAYS)
        wcount = 0
        hrcount = 0
        async for row in self._client.list_workouts(since=since):
            stmt = sqlite_insert(Workout).values(
                external_id=row.external_id,
                start_at=row.start_at,
                end_at=row.end_at,
                activity_type=row.activity_type,
                duration_min=row.duration_min,
                calories_kcal=row.calories_kcal,
                distance_m=row.distance_m,
                avg_hr=row.avg_hr,
                max_hr=row.max_hr,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(
                    start_at=row.start_at,
                    end_at=row.end_at,
                    activity_type=row.activity_type,
                    duration_min=row.duration_min,
                    calories_kcal=row.calories_kcal,
                    distance_m=row.distance_m,
                    avg_hr=row.avg_hr,
                    max_hr=row.max_hr,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
            wcount += 1

            async for hr in self._client.list_workout_hr_samples(
                workout_id=row.external_id,
                start_at=row.start_at,
                end_at=row.end_at,
            ):
                stmt = sqlite_insert(WorkoutHrSample).values(
                    workout_id=hr.workout_id,
                    sample_at=hr.sample_at,
                    bpm=hr.bpm,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["workout_id", "sample_at"],
                    set_=dict(bpm=hr.bpm),
                )
                self._db.execute(stmt)
                hrcount += 1
        self._db.commit()
        return wcount, hrcount
