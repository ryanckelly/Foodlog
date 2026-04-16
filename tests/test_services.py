import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from foodlog.db.models import Base, FoodEntry
from foodlog.models.schemas import FoodEntryCreate, FoodEntryUpdate, MealType
from foodlog.services.logging import EntryService


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def sample_entry() -> FoodEntryCreate:
    return FoodEntryCreate(
        meal_type=MealType.lunch,
        food_name="Chicken Breast",
        quantity=1.0,
        unit="serving",
        weight_g=150.0,
        calories=247.5,
        protein_g=46.5,
        carbs_g=0.0,
        fat_g=5.4,
        source="fatsecret",
        source_id="33691",
        raw_input="grilled chicken breast",
    )


def test_create_entry():
    session = make_session()
    svc = EntryService(session)
    entry = svc.create(sample_entry())
    assert entry.id is not None
    assert entry.food_name == "Chicken Breast"
    assert entry.calories == 247.5


def test_create_multiple_entries():
    session = make_session()
    svc = EntryService(session)
    entries_data = [
        sample_entry(),
        FoodEntryCreate(
            meal_type=MealType.lunch,
            food_name="White Rice",
            quantity=1.5,
            unit="cup",
            weight_g=280.0,
            calories=340.0,
            protein_g=6.0,
            carbs_g=74.0,
            fat_g=1.0,
            source="fatsecret",
            source_id="12345",
            raw_input="cup and a half of rice",
        ),
    ]
    results = svc.create_many(entries_data)
    assert len(results) == 2
    assert results[0].food_name == "Chicken Breast"
    assert results[1].food_name == "White Rice"


def test_get_entries_by_date():
    session = make_session()
    svc = EntryService(session)
    svc.create(sample_entry())
    entries = svc.get_by_date(datetime.date.today())
    assert len(entries) == 1
    assert entries[0].food_name == "Chicken Breast"


def test_get_entries_by_date_and_meal():
    session = make_session()
    svc = EntryService(session)
    svc.create(sample_entry())
    lunch = svc.get_by_date(datetime.date.today(), meal_type="lunch")
    dinner = svc.get_by_date(datetime.date.today(), meal_type="dinner")
    assert len(lunch) == 1
    assert len(dinner) == 0


def test_update_entry():
    session = make_session()
    svc = EntryService(session)
    entry = svc.create(sample_entry())
    updated = svc.update(entry.id, FoodEntryUpdate(quantity=2.0, calories=495.0))
    assert updated.quantity == 2.0
    assert updated.calories == 495.0
    assert updated.food_name == "Chicken Breast"


def test_delete_entry():
    session = make_session()
    svc = EntryService(session)
    entry = svc.create(sample_entry())
    assert svc.delete(entry.id) is True
    assert svc.get_by_date(datetime.date.today()) == []


def test_delete_nonexistent_entry():
    session = make_session()
    svc = EntryService(session)
    assert svc.delete(999) is False
