import datetime
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from foodlog.db.models import FoodEntry
from foodlog.models.schemas import FoodEntryCreate, FoodEntryUpdate


def _new_submission_id() -> str:
    """A short, unique token shared by all items from one log_food call."""
    return uuid.uuid4().hex


def backfill_submission_ids(session: Session, window_s: float = 5.0) -> int:
    """Assign submission_ids to legacy rows that predate the column.

    Best-effort historical grouping: rows with a NULL submission_id are walked in
    logged_at order and split into a new batch whenever the gap to the previous
    row exceeds ``window_s``. Mirrors the 5s clustering heuristic the body-sim
    analysis used before exact batching existed. Idempotent — only NULL rows are
    touched. Returns the number of rows updated.
    """
    rows = (
        session.query(FoodEntry)
        .filter(FoodEntry.submission_id.is_(None))
        .order_by(FoodEntry.logged_at)
        .all()
    )
    if not rows:
        return 0

    current_id = _new_submission_id()
    prev_at = rows[0].logged_at
    for row in rows:
        if (row.logged_at - prev_at).total_seconds() > window_s:
            current_id = _new_submission_id()
        row.submission_id = current_id
        prev_at = row.logged_at
    session.commit()
    return len(rows)


class EntryService:
    def __init__(self, session: Session):
        self.session = session

    def _build(self, data: FoodEntryCreate, submission_id: str) -> FoodEntry:
        return FoodEntry(
            meal_type=data.meal_type.value,
            food_name=data.food_name,
            quantity=data.quantity,
            unit=data.unit,
            weight_g=data.weight_g,
            calories=data.calories,
            protein_g=data.protein_g,
            carbs_g=data.carbs_g,
            fat_g=data.fat_g,
            fiber_g=data.fiber_g,
            sugar_g=data.sugar_g,
            sodium_mg=data.sodium_mg,
            source=data.source,
            source_id=data.source_id,
            raw_input=data.raw_input,
            submission_id=submission_id,
            consumed_at=data.consumed_at,
            logged_at=data.logged_at or datetime.datetime.now(),
        )

    def create(self, data: FoodEntryCreate) -> FoodEntry:
        entry = self._build(data, _new_submission_id())
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def create_many(self, items: list[FoodEntryCreate]) -> list[FoodEntry]:
        # One submission_id shared across every item in this batch, so downstream
        # analysis can group them exactly instead of clustering on timestamps.
        submission_id = _new_submission_id()
        entries = [self._build(data, submission_id) for data in items]
        for entry in entries:
            self.session.add(entry)
        self.session.commit()
        for e in entries:
            self.session.refresh(e)
        return entries

    def get_by_date(
        self, date: datetime.date, meal_type: str | None = None
    ) -> list[FoodEntry]:
        query = self.session.query(FoodEntry).filter(
            func.date(FoodEntry.logged_at) == date
        )
        if meal_type:
            query = query.filter(FoodEntry.meal_type == meal_type)
        return query.order_by(FoodEntry.logged_at).all()

    def get_by_range(
        self, start_date: datetime.date, end_date: datetime.date, meal_type: str | None = None
    ) -> list[FoodEntry]:
        query = self.session.query(FoodEntry).filter(
            func.date(FoodEntry.logged_at) >= start_date,
            func.date(FoodEntry.logged_at) <= end_date
        )
        if meal_type:
            query = query.filter(FoodEntry.meal_type == meal_type)
        return query.order_by(FoodEntry.logged_at.desc()).all()

    def update(self, entry_id: int, data: FoodEntryUpdate) -> FoodEntry | None:
        entry = self.session.get(FoodEntry, entry_id)
        if not entry:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            if hasattr(value, "value"):
                value = value.value
            setattr(entry, field, value)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def delete(self, entry_id: int) -> bool:
        entry = self.session.get(FoodEntry, entry_id)
        if not entry:
            return False
        self.session.delete(entry)
        self.session.commit()
        return True
