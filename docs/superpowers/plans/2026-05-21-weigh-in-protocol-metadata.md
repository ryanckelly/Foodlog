# Weigh-in Protocol Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Beads:** `foodlog-hg8` (phase-1) — run `bd show foodlog-hg8` for the canonical bead.

**Goal:** Capture weigh-in time-of-day metadata as a `weigh_in_protocol` column on `BodyComposition` and propagate a daily-aggregated flag to the body_sim rollup. This unlocks per-observation σ_obs in `foodlog-adu` (glycogen-water latent state) by letting that work assign tighter measurement noise to protocol-controlled morning weigh-ins than to ad-hoc evening / random-time weigh-ins.

**Context:** The user committed to consistent morning (post-void, pre-breakfast) weigh-ins from **2026-05-21** onward. Historical weigh-ins have variable timing — most are still morning, but two known evening/clothed outliers exist and are already filtered via `EXCLUDED_BODY_COMP_IDS`. This work adds soft metadata, not a filter.

**Architecture:**
1. Add `weigh_in_protocol VARCHAR(32) NULL` to the `body_composition` table via `ensure_columns` (SQLite `ALTER TABLE ADD COLUMN` — supports nullable no-default additions only).
2. At sync time (`_sync_body_composition`), compute the protocol from `measured_at` hour-of-day: `"controlled_morning"` if hour in [7, 11] inclusive AND `measured_at.date() >= 2026-05-21`; `"uncontrolled"` otherwise.
3. Add a one-time backfill CLI script `body_sim/tag_weigh_ins.py` that applies the same heuristic to existing rows. Idempotent.
4. Pipeline change: `rollup_body_comp` aggregates per-day to a boolean `weigh_in_protocol_controlled` column — `True` only if all that day's non-excluded weigh-ins are `controlled_morning`. Surface this through `build_daily_rollup`.
5. `validation.forward_walk` captures the flag in records but doesn't yet consume it (consumption is `foodlog-adu`'s job).
6. Tests for: schema migration, sync heuristic, pipeline aggregation, backfill script, validation propagation.

**Tech Stack:** SQLAlchemy 2.0, SQLite, pytest, FastAPI lifespan. No new dependencies.

**Cutoff date:** `WEIGH_IN_PROTOCOL_CUTOFF = datetime.date(2026, 5, 21)`. Defined as a module-level constant in a new `body_sim/weigh_in.py` so both the sync heuristic and the backfill script reference the same value.

**Protocol enum values (kept as strings, not Enum class, to match existing schema patterns):**
- `"controlled_morning"` — morning, post-void, pre-breakfast, established methodology
- `"uncontrolled"` — anything else (evening, clothed, off-time, etc.)
- `NULL` — pre-cutoff and not yet backfilled. Treated as `"uncontrolled"` by downstream consumers.

---

## File structure

### New files

```
body_sim/weigh_in.py                        protocol enum constants + classify_protocol() pure fn
body_sim/tag_weigh_ins.py                   CLI: idempotent backfill of weigh_in_protocol on existing rows
tests/body_sim/test_weigh_in.py             unit tests for classify_protocol
tests/body_sim/test_tag_weigh_ins.py        integration test for the backfill script
```

### Modified files

```
foodlog/db/models.py                        add weigh_in_protocol column to BodyComposition
foodlog/api/app.py                          register ensure_columns for body_composition
foodlog/services/health_sync.py             set protocol at upsert time
body_sim/pipeline.py                        rollup_body_comp emits weigh_in_protocol_controlled
body_sim/validation.py                      INPUT_COLUMNS gains protocol; _row_to_input passes through
tests/body_sim/test_pipeline_other.py       new test for rollup_body_comp protocol aggregation
tests/test_health_sync.py                   new test for sync-time protocol heuristic (if test file exists)
body_sim/CLAUDE.md                          document the new column + cutoff date
```

---

## Task 1: Add `body_sim/weigh_in.py` with the classification helper

**Files:**
- Create: `body_sim/weigh_in.py`
- Create: `tests/body_sim/test_weigh_in.py`

- [ ] **Step 1: Write the failing test**

Create `tests/body_sim/test_weigh_in.py`:

```python
import datetime

import pytest

from body_sim import weigh_in


def test_controlled_morning_after_cutoff():
    dt = datetime.datetime(2026, 5, 22, 9, 30)
    assert weigh_in.classify_protocol(dt) == "controlled_morning"


def test_uncontrolled_before_cutoff_even_if_morning():
    dt = datetime.datetime(2026, 5, 20, 9, 30)
    assert weigh_in.classify_protocol(dt) == "uncontrolled"


def test_uncontrolled_evening_after_cutoff():
    dt = datetime.datetime(2026, 5, 22, 19, 0)
    assert weigh_in.classify_protocol(dt) == "uncontrolled"


def test_boundary_hours_inclusive():
    # 7:00 and 11:00 are both controlled_morning
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 7, 0)) == "controlled_morning"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 11, 0)) == "controlled_morning"
    # 6:59 and 11:01 are not
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 6, 59)) == "uncontrolled"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 11, 1)) == "uncontrolled"


def test_boundary_date_inclusive():
    # 2026-05-21 morning = the cutoff date itself counts
    dt = datetime.datetime(2026, 5, 21, 9, 0)
    assert weigh_in.classify_protocol(dt) == "controlled_morning"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/body_sim/test_weigh_in.py -v`

Expected: FAIL — `ModuleNotFoundError: body_sim.weigh_in`.

- [ ] **Step 3: Implement the module**

Create `body_sim/weigh_in.py`:

```python
"""Weigh-in protocol classification.

A weigh-in is `controlled_morning` if it falls in the consistent morning
routine (07:00–11:00 inclusive, post-void, pre-breakfast) starting from the
cutoff date the user committed to the protocol. Everything else is
`uncontrolled` — variable hydration / gut state, possibly clothed, possibly
post-meal.

This metadata is soft. Excluded outliers (clothes-on, off-time evening
weigh-ins) are handled by ``pipeline.EXCLUDED_BODY_COMP_IDS`` and don't
appear here.

Used by:
- ``foodlog.services.health_sync._sync_body_composition`` to tag new rows
- ``body_sim.tag_weigh_ins`` to backfill existing rows
- ``body_sim.pipeline.rollup_body_comp`` to expose a daily-aggregate flag
- (future) ``foodlog-adu`` to set per-observation sigma_obs
"""

import datetime
from typing import Literal

Protocol = Literal["controlled_morning", "uncontrolled"]

# Date the user committed to consistent morning weigh-ins. Same morning slot
# applied retroactively is NOT trusted — there's no record of whether the
# pre-cutoff morning weigh-ins followed the same post-void / pre-breakfast
# discipline.
WEIGH_IN_PROTOCOL_CUTOFF: datetime.date = datetime.date(2026, 5, 21)

# Controlled-morning hour window, inclusive on both ends.
MORNING_HOUR_LO: int = 7
MORNING_HOUR_HI: int = 11


def classify_protocol(measured_at: datetime.datetime) -> Protocol:
    """Return the protocol label for a weigh-in datetime.

    Args:
        measured_at: timezone-naive local datetime of the weigh-in.

    Returns:
        ``"controlled_morning"`` if on/after the cutoff and within the
        morning hour window; ``"uncontrolled"`` otherwise.
    """
    if measured_at.date() < WEIGH_IN_PROTOCOL_CUTOFF:
        return "uncontrolled"
    # Inclusive on both ends: hour 7:00 through 11:59:59... but we treat
    # 11:00 itself as the upper bound (exclusive of 11:01+).
    hour = measured_at.hour
    minute = measured_at.minute
    if hour < MORNING_HOUR_LO:
        return "uncontrolled"
    if hour > MORNING_HOUR_HI:
        return "uncontrolled"
    if hour == MORNING_HOUR_HI and minute > 0:
        return "uncontrolled"
    return "controlled_morning"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/body_sim/test_weigh_in.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add body_sim/weigh_in.py tests/body_sim/test_weigh_in.py
git commit -m "feat(body_sim): add weigh_in.classify_protocol with 2026-05-21 cutoff (foodlog-hg8)"
```

---

## Task 2: Add the `weigh_in_protocol` column to BodyComposition

**Files:**
- Modify: `foodlog/db/models.py:169-179`
- Modify: `foodlog/api/app.py:45-56`

- [ ] **Step 1: Write a schema-level failing test**

Add to `tests/body_sim/test_pipeline_other.py`:

```python
def test_body_composition_has_weigh_in_protocol_column(in_memory_db):
    """Schema regression: the BodyComposition table must expose
    weigh_in_protocol so sync-time tagging + backfill have a place to write."""
    from foodlog.db.models import BodyComposition
    assert hasattr(BodyComposition, "weigh_in_protocol"), (
        "BodyComposition.weigh_in_protocol missing — schema migration "
        "(foodlog-hg8) not applied"
    )
```

If the `in_memory_db` fixture name differs, use whatever fixture exists in `tests/body_sim/conftest.py`. (Verify with `grep -n "@pytest.fixture" tests/body_sim/conftest.py`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/body_sim/test_pipeline_other.py::test_body_composition_has_weigh_in_protocol_column -v`

Expected: FAIL.

- [ ] **Step 3: Add the column to the model**

In `foodlog/db/models.py`, replace lines 169-179 (the `BodyComposition` class) with:

```python
class BodyComposition(Base):
    __tablename__ = "body_composition"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    measured_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Soft metadata: "controlled_morning" if the weigh-in followed the user's
    # established post-void pre-breakfast routine (07:00-11:00 local on/after
    # 2026-05-21); "uncontrolled" otherwise; NULL for un-backfilled
    # historical rows (treated as "uncontrolled" downstream).
    # See body_sim/weigh_in.py for the classification rule.
    weigh_in_protocol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
```

- [ ] **Step 4: Register the column in `ensure_columns` so existing SQLite DBs pick it up**

In `foodlog/api/app.py`, after the existing `ensure_columns(engine, "sleep_sessions", ...)` block (around line 56), add:

```python
ensure_columns(engine, "body_composition", {
    "weigh_in_protocol": "VARCHAR(32)",
})
```

- [ ] **Step 5: Run the schema test**

Run: `pytest tests/body_sim/test_pipeline_other.py::test_body_composition_has_weigh_in_protocol_column -v`

Expected: PASS.

- [ ] **Step 6: Run the full test suite for regressions**

Run: `pytest tests/ -x -q`

Expected: all PASS. If a test breaks because it constructs `BodyComposition(...)` positionally, switch it to keyword args. The new column is nullable so no test should require updating values.

- [ ] **Step 7: Commit**

```bash
git add foodlog/db/models.py foodlog/api/app.py tests/body_sim/test_pipeline_other.py
git commit -m "feat(db): add weigh_in_protocol column to body_composition (foodlog-hg8)"
```

---

## Task 3: Set the protocol at sync time

**Files:**
- Modify: `foodlog/services/health_sync.py:170-198`
- Test: add to existing `tests/test_health_sync.py` (if it exists; otherwise create `tests/test_health_sync_body_comp.py`)

- [ ] **Step 1: Check whether a health_sync test file already exists**

Run: `ls tests/ | grep -i sync`

If `tests/test_health_sync.py` exists, add to it. Otherwise the test goes in a new file.

- [ ] **Step 2: Write the failing test**

```python
# in tests/test_health_sync.py (or new file)
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from foodlog.db.models import BodyComposition
from foodlog.services.health_sync import HealthSyncService


@pytest.mark.asyncio
async def test_sync_body_composition_tags_protocol(session_factory):
    """Sync-time heuristic must tag morning post-cutoff rows controlled_morning
    and pre-cutoff or off-hour rows uncontrolled."""
    from foodlog.clients.google_health import BodyCompositionRow

    morning_post = BodyCompositionRow(
        external_id="test/morning_post",
        measured_at=datetime.datetime(2026, 5, 22, 9, 30),
        weight_kg=82.0, body_fat_pct=21.0, source="test",
    )
    evening_post = BodyCompositionRow(
        external_id="test/evening_post",
        measured_at=datetime.datetime(2026, 5, 22, 20, 0),
        weight_kg=82.5, body_fat_pct=21.1, source="test",
    )
    morning_pre = BodyCompositionRow(
        external_id="test/morning_pre",
        measured_at=datetime.datetime(2026, 5, 10, 9, 30),
        weight_kg=83.0, body_fat_pct=21.5, source="test",
    )

    async def fake_stream(since):
        for r in (morning_post, evening_post, morning_pre):
            yield r

    db = session_factory()
    client = MagicMock()
    client.list_body_composition = fake_stream
    svc = HealthSyncService(db=db, client=client)
    await svc._sync_body_composition()

    rows = {r.external_id: r for r in db.query(BodyComposition).all()}
    assert rows["test/morning_post"].weigh_in_protocol == "controlled_morning"
    assert rows["test/evening_post"].weigh_in_protocol == "uncontrolled"
    assert rows["test/morning_pre"].weigh_in_protocol == "uncontrolled"
```

If the existing fixture name is not `session_factory`, find it in `tests/conftest.py` (`grep -n "def.*session" tests/conftest.py`) and use that.

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/test_health_sync.py::test_sync_body_composition_tags_protocol -v`

Expected: FAIL — `weigh_in_protocol` field on the row is None.

- [ ] **Step 4: Update `_sync_body_composition` to set the protocol**

In `foodlog/services/health_sync.py`, replace the `_sync_body_composition` method body (around lines 170-198):

```python
    async def _sync_body_composition(self) -> int:
        from body_sim.weigh_in import classify_protocol

        since = cursor_for(self._db, BodyComposition, "measured_at", DEFAULT_BACKFILL_DAYS)
        rows = [r async for r in self._client.list_body_composition(since=since)]
        for row in rows:
            protocol = classify_protocol(row.measured_at)
            stmt = sqlite_insert(BodyComposition).values(
                external_id=row.external_id,
                measured_at=row.measured_at,
                weight_kg=row.weight_kg,
                body_fat_pct=row.body_fat_pct,
                source=row.source,
                weigh_in_protocol=protocol,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(
                    measured_at=row.measured_at,
                    weight_kg=row.weight_kg,
                    body_fat_pct=row.body_fat_pct,
                    source=row.source,
                    weigh_in_protocol=protocol,
                ),
            )
            self._db.execute(stmt)
        self._db.commit()
        return len(rows)
```

The local `from body_sim.weigh_in import ...` keeps the `foodlog` package's body_sim coupling explicit and minimal — top-level cycles are avoided.

- [ ] **Step 5: Run the test**

Run: `pytest tests/test_health_sync.py::test_sync_body_composition_tags_protocol -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add foodlog/services/health_sync.py tests/test_health_sync.py
git commit -m "feat(sync): tag body_composition with weigh_in_protocol at upsert (foodlog-hg8)"
```

---

## Task 4: Backfill CLI for existing rows

**Files:**
- Create: `body_sim/tag_weigh_ins.py`
- Create: `tests/body_sim/test_tag_weigh_ins.py`

- [ ] **Step 1: Write the failing test**

Create `tests/body_sim/test_tag_weigh_ins.py`:

```python
import datetime

import pytest

from foodlog.db.models import BodyComposition
from body_sim.tag_weigh_ins import backfill_protocol


def _make_row(external_id: str, measured_at: datetime.datetime) -> BodyComposition:
    return BodyComposition(
        external_id=external_id,
        measured_at=measured_at,
        weight_kg=82.0, body_fat_pct=21.0, source="test",
    )


def test_backfill_tags_existing_rows(in_memory_session):
    db = in_memory_session
    db.add(_make_row("a", datetime.datetime(2026, 5, 22, 9, 30)))  # controlled
    db.add(_make_row("b", datetime.datetime(2026, 5, 22, 20, 0)))  # uncontrolled
    db.add(_make_row("c", datetime.datetime(2026, 5, 10, 9, 30)))  # uncontrolled (pre-cutoff)
    db.commit()

    n_updated = backfill_protocol(db, dry_run=False)
    assert n_updated == 3

    rows = {r.external_id: r for r in db.query(BodyComposition).all()}
    assert rows["a"].weigh_in_protocol == "controlled_morning"
    assert rows["b"].weigh_in_protocol == "uncontrolled"
    assert rows["c"].weigh_in_protocol == "uncontrolled"


def test_backfill_is_idempotent(in_memory_session):
    db = in_memory_session
    db.add(_make_row("a", datetime.datetime(2026, 5, 22, 9, 30)))
    db.commit()
    backfill_protocol(db, dry_run=False)
    # Second invocation should be a no-op for already-tagged rows
    n_updated = backfill_protocol(db, dry_run=False, only_null=True)
    assert n_updated == 0


def test_backfill_dry_run_does_not_write(in_memory_session):
    db = in_memory_session
    db.add(_make_row("a", datetime.datetime(2026, 5, 22, 9, 30)))
    db.commit()
    n_would_update = backfill_protocol(db, dry_run=True)
    assert n_would_update == 1
    row = db.query(BodyComposition).filter_by(external_id="a").one()
    assert row.weigh_in_protocol is None
```

If `in_memory_session` is not the fixture name, check `tests/body_sim/conftest.py` for the right name.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/body_sim/test_tag_weigh_ins.py -v`

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the script**

Create `body_sim/tag_weigh_ins.py`:

```python
"""Backfill weigh_in_protocol on existing body_composition rows.

Sync time (foodlog/services/health_sync.py) tags new rows at upsert. This
script handles the one-time backfill of rows that existed before the column
was added. Idempotent — pass --only-null (the default) to skip rows that
already have a value.

Usage:
    python -m body_sim.tag_weigh_ins                # dry-run, only-null
    python -m body_sim.tag_weigh_ins --apply        # write
    python -m body_sim.tag_weigh_ins --apply --force  # overwrite existing
"""

import argparse
from typing import TYPE_CHECKING

from body_sim.weigh_in import classify_protocol

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def backfill_protocol(
    db: "Session", *, dry_run: bool = True, only_null: bool = True
) -> int:
    """Apply the protocol classifier to body_composition rows.

    Args:
        db: SQLAlchemy session.
        dry_run: if True, count rows that would be updated but don't write.
        only_null: if True, skip rows that already have a protocol set.

    Returns:
        Number of rows updated (or that would be updated in dry_run mode).
    """
    from foodlog.db.models import BodyComposition  # avoid import cycle

    q = db.query(BodyComposition)
    if only_null:
        q = q.filter(BodyComposition.weigh_in_protocol.is_(None))
    rows = q.all()
    n = 0
    for row in rows:
        new_protocol = classify_protocol(row.measured_at)
        if row.weigh_in_protocol != new_protocol:
            n += 1
            if not dry_run:
                row.weigh_in_protocol = new_protocol
    if not dry_run:
        db.commit()
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write changes (default: dry run)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite existing values (default: only fill NULL)",
    )
    args = parser.parse_args()

    from foodlog.db.database import get_engine, get_session_factory

    Session = get_session_factory(get_engine())
    db = Session()
    try:
        n = backfill_protocol(db, dry_run=not args.apply, only_null=not args.force)
        action = "updated" if args.apply else "would update"
        print(f"{action} {n} rows")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/body_sim/test_tag_weigh_ins.py -v`

Expected: all PASS.

- [ ] **Step 5: Apply to the live DB (after a dry-run)**

The live DB lives inside the foodlog container. To run the backfill against it:

```bash
# Dry-run first
docker exec foodlog python -m body_sim.tag_weigh_ins
# Apply if the count looks right
docker exec foodlog python -m body_sim.tag_weigh_ins --apply
```

Expected: dry-run prints a row count matching the body_composition table size; apply prints the same number and updates the DB. Re-running with `--apply` should print `updated 0 rows` (idempotency).

If `docker exec` fails or the script raises an import error inside the container, the body_sim package may not be installed in the runtime image. The fallback is to run it on the host against the SQLite file directly:

```bash
.venv/bin/python -m body_sim.tag_weigh_ins                  # dry-run (uses FOODLOG_DATABASE_URL or default)
.venv/bin/python -m body_sim.tag_weigh_ins --apply          # write
```

- [ ] **Step 6: Commit**

```bash
git add body_sim/tag_weigh_ins.py tests/body_sim/test_tag_weigh_ins.py
git commit -m "feat(body_sim): one-time backfill script for weigh_in_protocol (foodlog-hg8)"
```

---

## Task 5: Surface the daily-aggregate flag in `rollup_body_comp`

**Files:**
- Modify: `body_sim/pipeline.py:282-325` (the `rollup_body_comp` function)
- Test: `tests/body_sim/test_pipeline_other.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/body_sim/test_pipeline_other.py`:

```python
def test_rollup_body_comp_emits_protocol_controlled_flag(in_memory_session):
    """A day with all weigh-ins flagged controlled_morning gets
    weigh_in_protocol_controlled=True; a day with any uncontrolled weigh-in
    gets False; a day with no weigh-ins gets False."""
    import datetime
    from foodlog.db.models import BodyComposition
    from body_sim import pipeline

    db = in_memory_session
    db.add(BodyComposition(
        external_id="a", measured_at=datetime.datetime(2026, 5, 22, 9, 0),
        weight_kg=82.0, body_fat_pct=21.0, source="test",
        weigh_in_protocol="controlled_morning",
    ))
    db.add(BodyComposition(
        external_id="b", measured_at=datetime.datetime(2026, 5, 23, 9, 0),
        weight_kg=82.5, body_fat_pct=21.1, source="test",
        weigh_in_protocol="controlled_morning",
    ))
    db.add(BodyComposition(
        external_id="c", measured_at=datetime.datetime(2026, 5, 23, 19, 0),
        weight_kg=83.0, body_fat_pct=21.2, source="test",
        weigh_in_protocol="uncontrolled",
    ))
    db.commit()

    out = pipeline.rollup_body_comp(
        db, datetime.date(2026, 5, 22), datetime.date(2026, 5, 24)
    )
    assert out.loc[datetime.datetime(2026, 5, 22), "weigh_in_protocol_controlled"] is True
    assert out.loc[datetime.datetime(2026, 5, 23), "weigh_in_protocol_controlled"] is False
    assert out.loc[datetime.datetime(2026, 5, 24), "weigh_in_protocol_controlled"] is False
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/body_sim/test_pipeline_other.py::test_rollup_body_comp_emits_protocol_controlled_flag -v`

Expected: FAIL — KeyError on `weigh_in_protocol_controlled`.

- [ ] **Step 3: Update `rollup_body_comp`**

In `body_sim/pipeline.py`, replace `rollup_body_comp` (lines 282-325) with:

```python
def rollup_body_comp(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    """Aggregate body_composition to one row per day.

    Columns: weight_kg (median), bf_pct (median), n_weighins,
    weigh_in_protocol_controlled (bool — True iff every non-excluded
    weigh-in that day is tagged ``controlled_morning``).

    Multiple readings on the same day are reduced to the median for both
    weight and body-fat percentage. Days with no readings return NaN for
    weight_kg/bf_pct, 0 for n_weighins, False for the protocol flag.
    """
    rows = (
        session.query(BodyComposition)
        .filter(
            BodyComposition.measured_at >= datetime.datetime.combine(start, datetime.time()),
            BodyComposition.measured_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
            ~BodyComposition.external_id.in_(EXCLUDED_BODY_COMP_IDS),
        )
        .all()
    )
    per_day: dict[datetime.date, list[BodyComposition]] = {}
    for r in rows:
        per_day.setdefault(r.measured_at.date(), []).append(r)

    idx = _date_index(start, end)
    records = []
    for ts in idx:
        d = ts.date()
        rs = per_day.get(d, [])
        if rs:
            weights = [r.weight_kg for r in rs if r.weight_kg is not None]
            bfs = [r.body_fat_pct for r in rs if r.body_fat_pct is not None]
            all_controlled = all(
                r.weigh_in_protocol == "controlled_morning" for r in rs
            )
            records.append(
                {
                    "weight_kg": float(np.median(weights)) if weights else np.nan,
                    "bf_pct": float(np.median(bfs)) if bfs else np.nan,
                    "n_weighins": len(rs),
                    "weigh_in_protocol_controlled": bool(all_controlled),
                }
            )
        else:
            records.append({
                "weight_kg": np.nan,
                "bf_pct": np.nan,
                "n_weighins": 0,
                "weigh_in_protocol_controlled": False,
            })
    df = pd.DataFrame(records, index=idx)
    # Match the bool-identity convention used by rollup_food.intake_logged
    df["weigh_in_protocol_controlled"] = df["weigh_in_protocol_controlled"].astype(object)
    return df
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/body_sim/test_pipeline_other.py::test_rollup_body_comp_emits_protocol_controlled_flag -v`

Expected: PASS.

- [ ] **Step 5: Run the full pipeline test suite**

Run: `pytest tests/body_sim/test_pipeline_other.py tests/body_sim/test_pipeline_assembly.py -v`

Expected: all PASS. The `weigh_in_protocol_controlled` column is now in every `build_daily_rollup` output through normal concat.

- [ ] **Step 6: Commit**

```bash
git add body_sim/pipeline.py tests/body_sim/test_pipeline_other.py
git commit -m "feat(body_sim): rollup_body_comp emits weigh_in_protocol_controlled (foodlog-hg8)"
```

---

## Task 6: Propagate the flag through `validation.forward_walk`

**Files:**
- Modify: `body_sim/validation.py:103-118`
- Test: `tests/body_sim/test_validation.py`

The flag isn't consumed yet — that's `foodlog-adu`'s job. But the walk's output DataFrame should carry it so notebook 04 (and the future Bayesian fit) can stratify metrics by protocol if useful.

- [ ] **Step 1: Write the failing test**

Add to `tests/body_sim/test_validation.py`:

```python
def test_forward_walk_propagates_protocol_flag():
    """The protocol_controlled bool from the rollup should appear in the
    long-form walk DataFrame alongside observed_weight_kg."""
    df = _synthetic_rollup(n_days=14)
    df["weigh_in_protocol_controlled"] = False
    df.loc[df.index[0], "weigh_in_protocol_controlled"] = True
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=2, seed=0
    )
    assert "weigh_in_protocol_controlled" in out.columns
    # The flag for day 0 should be True
    day_0 = out[out["date"] == df.index[0]]
    assert day_0["weigh_in_protocol_controlled"].iloc[0] is True
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/body_sim/test_validation.py::test_forward_walk_propagates_protocol_flag -v`

Expected: FAIL.

- [ ] **Step 3: Update the records loop in `forward_walk`**

In `body_sim/validation.py`, within the inner loop (around line 103-117), update the record-building dict to include the new column. Replace the `records.append({...})` block with:

```python
                records.append(
                    {
                        "date": ts,
                        "sample": s,
                        "predicted_weight_kg": float(result.predicted_weight_kg[s, d_offset]),
                        "observed_weight_kg": (
                            float(chunk.iloc[d_offset]["weight_kg"])
                            if pd.notna(chunk.iloc[d_offset]["weight_kg"])
                            else np.nan
                        ),
                        "fat_mass_kg": float(result.fat_mass_kg[s, d_offset]),
                        "lean_mass_kg": float(result.lean_mass_kg[s, d_offset]),
                        "body_fat_pct": float(result.body_fat_pct[s, d_offset]),
                        "weigh_in_protocol_controlled": bool(
                            chunk.iloc[d_offset].get("weigh_in_protocol_controlled", False)
                        ),
                    }
                )
```

The `.get(..., False)` default means tests with synthetic rollups that don't include the flag still work.

- [ ] **Step 4: Run the test**

Run: `pytest tests/body_sim/test_validation.py::test_forward_walk_propagates_protocol_flag -v`

Expected: PASS.

- [ ] **Step 5: Run the full validation test suite**

Run: `pytest tests/body_sim/test_validation.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add body_sim/validation.py tests/body_sim/test_validation.py
git commit -m "feat(body_sim): propagate weigh_in_protocol_controlled through forward_walk (foodlog-hg8)"
```

---

## Task 7: Apply the backfill to the live DB and update CLAUDE.md

- [ ] **Step 1: Run the backfill against the live DB**

```bash
docker exec foodlog python -m body_sim.tag_weigh_ins
# Confirm count looks right (should equal total body_composition row count)
docker exec foodlog python -m body_sim.tag_weigh_ins --apply
# Re-run for idempotency check
docker exec foodlog python -m body_sim.tag_weigh_ins
```

Expected: final dry-run prints `would update 0 rows`.

- [ ] **Step 2: Sanity-check the live counts**

```bash
docker exec foodlog sqlite3 /data/foodlog.db \
  "SELECT weigh_in_protocol, COUNT(*) FROM body_composition GROUP BY weigh_in_protocol"
```

(Verify DB path matches the container's actual mount; if different, run via `python -c` against the SQLAlchemy session instead.)

Expected: a count for `controlled_morning` (today's onward-going weigh-in plus any historical morning hits ≥2026-05-21) and a count for `uncontrolled` (everything else).

- [ ] **Step 3: Update body_sim/CLAUDE.md**

In `body_sim/CLAUDE.md`, after the "Data exclusions" section, add a new section:

```markdown
## Weigh-in protocol metadata

Each `body_composition` row carries a `weigh_in_protocol` string column:

- `"controlled_morning"` — measured in the user's established 07:00–11:00 post-void, pre-breakfast routine on or after the cutoff date 2026-05-21.
- `"uncontrolled"` — any other time-of-day, any pre-cutoff weigh-in.
- `NULL` — pre-2026-05-21 rows that haven't been backfilled yet (rare; treated as `"uncontrolled"` downstream).

The classification is implemented as a pure function `body_sim.weigh_in.classify_protocol(datetime) -> Protocol`. Sync (`foodlog.services.health_sync._sync_body_composition`) applies it at upsert; the one-time backfill of pre-existing rows is `python -m body_sim.tag_weigh_ins --apply`.

The daily rollup surfaces this as a `weigh_in_protocol_controlled: bool` column on `rollup_body_comp` output — `True` only if every non-excluded weigh-in that day is `controlled_morning`. The flag is propagated through `validation.forward_walk` for downstream consumers.

This metadata is **soft** — not a filter. Filtering of methodologically-broken rows continues to happen via `EXCLUDED_BODY_COMP_IDS` (see "Data exclusions" above). Phase 2 (`foodlog-adu`) uses this column to assign tighter σ_obs to controlled rows in the PyMC likelihood.
```

- [ ] **Step 4: Commit the docs**

```bash
git add body_sim/CLAUDE.md
git commit -m "docs(body_sim): document weigh_in_protocol metadata + cutoff (foodlog-hg8)"
```

---

## Task 8: Close out

- [ ] **Step 1: Re-execute notebook 04**

```bash
.venv/bin/jupyter nbconvert --to notebook --execute notebooks/04_hall_baseline.ipynb \
    --output 04_hall_baseline.ipynb --ExecutePreprocessor.timeout=600
```

Expected: no errors. Metrics unchanged — this is plumbing.

- [ ] **Step 2: Full test sweep**

Run: `pytest tests/ -x -q`

Expected: all PASS.

- [ ] **Step 3: Close the bead**

```bash
bd close foodlog-hg8 --reason="weigh_in_protocol column added, sync tags new rows, backfill script applied to live DB, rollup + forward_walk propagate the daily-aggregate flag. Ready for foodlog-adu to consume."
```

- [ ] **Step 4: Session-close protocol**

```bash
git pull --rebase
bd dolt push 2>&1 || true
git push
git status
```

---

## Self-review notes

- **Spec coverage:** schema (Task 2), sync heuristic (Task 3), backfill script (Task 4), pipeline aggregation (Task 5), validation propagation (Task 6), live-DB backfill (Task 7). Every acceptance criterion from the bead is covered.
- **Pure-function helper first:** `weigh_in.classify_protocol` is the single source of truth for the rule. Sync and backfill both call it.
- **Idempotency:** backfill defaults to `only_null=True`. Re-runs are safe.
- **No placeholders:** every code change is fully spelled out.
- **Type consistency:** `Protocol` literal type, `weigh_in_protocol` (string column) vs `weigh_in_protocol_controlled` (bool aggregate) names are kept distinct so downstream code can't accidentally compare a string to a bool.
- **Closure:** Task 8 closes the bead and pushes.
