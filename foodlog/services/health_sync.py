"""Orchestrate Google Health → FoodLog DB sync.

Per-table cursor derived from data timestamps (robust against clock skew).
All writes use upsert-on-conflict keyed by ``external_id`` for idempotency.
Runs synchronously inside a dashboard request handler.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

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

logger = logging.getLogger(__name__)

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
        """Run every per-type sync. One failing type must NOT kill the others —
        Google Health's data types have per-type quirks (unsupported `list`
        action, different filter grammar, different response shapes) and we
        want a partial success to still populate the dashboard."""
        result = SyncResult()

        async def _run(
            name: str,
            fn: Callable[[], Awaitable[int]],
            brittle: bool = False,
        ) -> None:
            try:
                result.rows_upserted[name] = await fn()
            except RateLimited:
                result.ok = False
                result.rate_limited = True
                logger.warning("health sync rate-limited on %s", name)
            except GoogleHealthError as e:
                if brittle:
                    # Known-brittle endpoints (e.g. sleep list, which
                    # consistently 500s for this account regardless of filter)
                    # should not flip the stale banner. Log and move on.
                    logger.info(
                        "health sync tolerated google-error on %s: %s",
                        name, e,
                    )
                    result.rows_upserted[name] = 0
                else:
                    result.ok = False
                    result.server_error = True
                    logger.warning("health sync google-error on %s: %s", name, e)
            except Exception:
                # Parser mismatch, KeyError on unexpected response shape, etc.
                result.ok = False
                logger.exception("health sync crashed on %s (continuing)", name)

        await _run("daily_activity", self._sync_daily_activity)
        await _run("body_composition", self._sync_body_composition)
        await _run("resting_heart_rate", self._sync_resting_hr)
        await _run("sleep_sessions", self._sync_sleep, brittle=True)

        # workouts + hr_samples are synced together but reported separately.
        try:
            wcount, hrcount = await self._sync_workouts_with_hr()
            result.rows_upserted["workouts"] = wcount
            result.rows_upserted["workout_hr_samples"] = hrcount
        except RateLimited:
            result.ok = False
            result.rate_limited = True
            logger.warning("health sync rate-limited on workouts")
        except GoogleHealthError as e:
            result.ok = False
            result.server_error = True
            logger.warning("health sync google-error on workouts: %s", e)
        except Exception:
            result.ok = False
            logger.exception("health sync crashed on workouts (continuing)")

        return result

    # ---------- per-table sync methods ----------
    #
    # IMPORTANT: each method first DRAINS its async iterator fully before
    # opening a SQLite transaction. Holding a write transaction while making
    # further async HTTP calls to Google deadlocks against any concurrent
    # dashboard request that also tries to write (SQLite allows only one
    # writer). The 2026-04-24 deploy hit exactly this the moment the user
    # refreshed the feed twice: second request failed with
    # `OperationalError: database is locked`. Drain-then-write keeps the
    # transaction window small (ms), eliminating the race.

    async def _sync_daily_activity(self) -> int:
        # Always re-fetch today and yesterday; daily totals can change late.
        today = datetime.date.today()
        since = datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time.min)
        rows = [r async for r in self._client.list_daily_activity(since=since)]
        for row in rows:
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
        self._db.commit()
        return len(rows)

    async def _sync_body_composition(self) -> int:
        since = cursor_for(self._db, BodyComposition, "measured_at", DEFAULT_BACKFILL_DAYS)
        rows = [r async for r in self._client.list_body_composition(since=since)]
        for row in rows:
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
        self._db.commit()
        return len(rows)

    async def _sync_resting_hr(self) -> int:
        since = cursor_for(self._db, RestingHeartRate, "measured_at", DEFAULT_BACKFILL_DAYS)
        rows = [r async for r in self._client.list_resting_heart_rate(since=since)]
        for row in rows:
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
        self._db.commit()
        return len(rows)

    async def _sync_sleep(self) -> int:
        # Sleep has two quirks:
        #   1. Only filter member is civil_end_time (device-local) — see
        #      FILTER_FIELDS comment.
        #   2. Google 500s intermittently on wider queries (confirmed
        #      deterministic for a 14-day look-back on one test account). A
        #      3-day window is tight enough to avoid that while still
        #      catching recent sessions on each on-presence sync.
        since = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=3)
        rows = [r async for r in self._client.list_sleep_sessions(since=since)]
        for row in rows:
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
        self._db.commit()
        return len(rows)

    async def _sync_workouts_with_hr(self) -> tuple[int, int]:
        # Same rationale as _sync_sleep: exercise's civil_start_time filter
        # is device-local but our cursor is UTC. Use fixed 14-day look-back.
        since = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=14)
        workouts = [w async for w in self._client.list_workouts(since=since)]

        # Performance: heart-rate samples paginate at ~50 per page. A 46-min
        # walk can emit thousands of samples → dozens of HTTP round-trips per
        # workout. Re-fetching them on every on-presence sync was taking
        # tens of seconds. Skip any workout whose samples are already in DB
        # (upserts are idempotent, so one successful pull is enough).
        already_synced = {
            wid for (wid,) in self._db.execute(
                select(WorkoutHrSample.workout_id).distinct()
            ).all()
        }
        hr_by_workout: list[tuple[str, list]] = []
        # Google doesn't emit max-HR on the exercise record, so derive it from
        # HR samples — either freshly fetched or already in DB.
        max_hr_per_workout: dict[str, int | None] = {}
        for w in workouts:
            if w.external_id in already_synced:
                max_hr_per_workout[w.external_id] = self._db.execute(
                    select(func.max(WorkoutHrSample.bpm))
                    .where(WorkoutHrSample.workout_id == w.external_id)
                ).scalar()
                continue
            samples = [
                s async for s in self._client.list_workout_hr_samples(
                    workout_id=w.external_id,
                    start_at=w.start_at,
                    end_at=w.end_at,
                )
            ]
            hr_by_workout.append((w.external_id, samples))
            max_hr_per_workout[w.external_id] = max(
                (s.bpm for s in samples), default=None,
            )

        hrcount = 0
        for w in workouts:
            derived_max_hr = w.max_hr or max_hr_per_workout.get(w.external_id)
            stmt = sqlite_insert(Workout).values(
                external_id=w.external_id,
                start_at=w.start_at,
                end_at=w.end_at,
                activity_type=w.activity_type,
                duration_min=w.duration_min,
                calories_kcal=w.calories_kcal,
                distance_m=w.distance_m,
                avg_hr=w.avg_hr,
                max_hr=derived_max_hr,
                source=w.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(
                    start_at=w.start_at,
                    end_at=w.end_at,
                    activity_type=w.activity_type,
                    duration_min=w.duration_min,
                    calories_kcal=w.calories_kcal,
                    distance_m=w.distance_m,
                    avg_hr=w.avg_hr,
                    max_hr=derived_max_hr,
                    source=w.source,
                ),
            )
            self._db.execute(stmt)
        for _, samples in hr_by_workout:
            for hr in samples:
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
        return len(workouts), hrcount
