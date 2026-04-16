import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from foodlog.db.models import FoodEntry
from foodlog.models.schemas import FoodEntryCreate, FoodEntryUpdate


class EntryService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, data: FoodEntryCreate) -> FoodEntry:
        entry = FoodEntry(
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
            logged_at=data.logged_at or datetime.datetime.now(),
        )
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def create_many(self, items: list[FoodEntryCreate]) -> list[FoodEntry]:
        entries = []
        for data in items:
            entry = FoodEntry(
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
                logged_at=data.logged_at or datetime.datetime.now(),
            )
            self.session.add(entry)
            entries.append(entry)
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
