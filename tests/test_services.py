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


def test_get_entries_by_range():
    session = make_session()
    svc = EntryService(session)
    svc.create(sample_entry())
    start_date = datetime.date.today() - datetime.timedelta(days=1)
    end_date = datetime.date.today()
    
    entries = svc.get_by_range(start_date, end_date)
    assert len(entries) > 0


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


# --- Summary Service Tests ---

from foodlog.services.nutrition import SummaryService


def test_daily_summary():
    session = make_session()
    entry_svc = EntryService(session)
    entry_svc.create(sample_entry())
    entry_svc.create(
        FoodEntryCreate(
            meal_type=MealType.lunch,
            food_name="White Rice",
            quantity=1.5,
            unit="cup",
            calories=340.0,
            protein_g=6.0,
            carbs_g=74.0,
            fat_g=1.0,
            source="fatsecret",
            raw_input="rice",
        )
    )

    summary_svc = SummaryService(session)
    summary = summary_svc.daily(datetime.date.today())
    assert summary.total_calories == 587.5
    assert summary.total_protein_g == 52.5
    assert len(summary.meals) == 1
    assert summary.meals[0].meal_type == "lunch"
    assert summary.meals[0].entry_count == 2


def test_daily_summary_multiple_meals():
    session = make_session()
    entry_svc = EntryService(session)
    entry_svc.create(sample_entry())
    entry_svc.create(
        FoodEntryCreate(
            meal_type=MealType.snack,
            food_name="Apple",
            quantity=1.0,
            unit="medium",
            calories=95.0,
            protein_g=0.5,
            carbs_g=25.0,
            fat_g=0.3,
            source="usda",
            raw_input="apple",
        )
    )

    summary_svc = SummaryService(session)
    summary = summary_svc.daily(datetime.date.today())
    assert summary.total_calories == 342.5
    assert len(summary.meals) == 2


def test_daily_summary_empty():
    session = make_session()
    summary_svc = SummaryService(session)
    summary = summary_svc.daily(datetime.date.today())
    assert summary.total_calories == 0.0
    assert summary.meals == []


def test_range_summary():
    session = make_session()
    entry_svc = EntryService(session)
    entry_svc.create(sample_entry())

    summary_svc = SummaryService(session)
    today = datetime.date.today()
    result = summary_svc.range(today, today)
    assert result.total_calories == 247.5
    assert result.days == 1
    assert result.avg_daily_calories == 247.5


# --- Search Service Tests ---

import pytest

from foodlog.models.schemas import FoodSearchResult
from foodlog.services.search import SearchService


class FakeFatSecretClient:
    def __init__(self, results: list[FoodSearchResult]):
        self._results = results

    async def search(self, query: str, max_results: int = 10):
        return self._results


class FakeUSDAClient:
    def __init__(self, results: list[FoodSearchResult]):
        self._results = results

    async def search(self, query: str, page_size: int = 10):
        return self._results


def make_result(name, source, food_id="1"):
    return FoodSearchResult(
        food_id=food_id,
        food_name=name,
        source=source,
        calories=100.0,
        protein_g=10.0,
        carbs_g=20.0,
        fat_g=5.0,
        serving_description="Per 100g",
    )


@pytest.mark.asyncio
async def test_search_fatsecret_primary():
    fs = FakeFatSecretClient([make_result("Chicken", "fatsecret")])
    usda = FakeUSDAClient([make_result("Chicken", "usda")])
    svc = SearchService(fatsecret=fs, usda=usda)
    results = await svc.search("chicken")
    assert len(results) == 1
    assert results[0].source == "fatsecret"


@pytest.mark.asyncio
async def test_search_fallback_to_usda():
    fs = FakeFatSecretClient([])
    usda = FakeUSDAClient([make_result("Chicken", "usda")])
    svc = SearchService(fatsecret=fs, usda=usda)
    results = await svc.search("chicken")
    assert len(results) == 1
    assert results[0].source == "usda"


@pytest.mark.asyncio
async def test_search_no_fatsecret():
    usda = FakeUSDAClient([make_result("Chicken", "usda")])
    svc = SearchService(fatsecret=None, usda=usda)
    results = await svc.search("chicken")
    assert len(results) == 1
    assert results[0].source == "usda"


@pytest.mark.asyncio
async def test_search_no_clients():
    svc = SearchService(fatsecret=None, usda=None)
    with pytest.raises(RuntimeError, match="No food database APIs configured"):
        await svc.search("chicken")
