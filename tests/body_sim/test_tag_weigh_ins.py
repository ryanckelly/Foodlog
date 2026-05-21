import datetime

import pytest

from foodlog.db.models import BodyComposition
from body_sim.tag_weigh_ins import backfill_protocol


def _make_row(external_id: str, measured_at: datetime.datetime) -> BodyComposition:
    return BodyComposition(
        external_id=external_id,
        measured_at=measured_at,
        weight_kg=82.0,
        body_fat_pct=21.0,
        source="test",
    )


def test_backfill_tags_existing_rows(session):
    session.add(_make_row("a", datetime.datetime(2026, 5, 22, 9, 30)))  # controlled
    session.add(_make_row("b", datetime.datetime(2026, 5, 22, 20, 0)))  # uncontrolled
    session.add(_make_row("c", datetime.datetime(2026, 5, 10, 9, 30)))  # pre-cutoff
    session.commit()

    n_updated = backfill_protocol(session, dry_run=False)
    assert n_updated == 3

    rows = {r.external_id: r for r in session.query(BodyComposition).all()}
    assert rows["a"].weigh_in_protocol == "controlled_morning"
    assert rows["b"].weigh_in_protocol == "uncontrolled"
    assert rows["c"].weigh_in_protocol == "uncontrolled"


def test_backfill_is_idempotent(session):
    session.add(_make_row("a", datetime.datetime(2026, 5, 22, 9, 30)))
    session.commit()
    backfill_protocol(session, dry_run=False)
    n_updated = backfill_protocol(session, dry_run=False, only_null=True)
    assert n_updated == 0


def test_backfill_dry_run_does_not_write(session):
    session.add(_make_row("a", datetime.datetime(2026, 5, 22, 9, 30)))
    session.commit()
    n_would_update = backfill_protocol(session, dry_run=True)
    assert n_would_update == 1
    row = session.query(BodyComposition).filter_by(external_id="a").one()
    assert row.weigh_in_protocol is None
