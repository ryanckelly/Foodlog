"""Backfill ``weigh_in_protocol`` on existing ``body_composition`` rows.

Sync time (``foodlog.services.health_sync._sync_body_composition``) tags new
rows at upsert. This script handles the one-time backfill of rows that
existed before the column was added. Idempotent — defaults to ``only_null``
so re-running won't overwrite already-tagged rows.

Usage::

    python -m body_sim.tag_weigh_ins              # dry-run, only-null
    python -m body_sim.tag_weigh_ins --apply      # write
    python -m body_sim.tag_weigh_ins --apply --force   # overwrite existing
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
        Number of rows updated (or that would be updated in dry-run mode).
    """
    from foodlog.db.models import BodyComposition  # avoid import cycle at module load

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

    SessionFactory = get_session_factory(get_engine())
    db = SessionFactory()
    try:
        n = backfill_protocol(db, dry_run=not args.apply, only_null=not args.force)
        action = "updated" if args.apply else "would update"
        print(f"{action} {n} rows")
    finally:
        db.close()


if __name__ == "__main__":
    main()
