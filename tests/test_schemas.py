import datetime

import pytest
from pydantic import ValidationError

from foodlog.models.schemas import (
    FoodEntryCreate,
    FoodEntryResponse,
    FoodSearchResult,
    DailySummary,
    MealSummary,
)


def test_food_entry_create_valid():
    entry = FoodEntryCreate(
        meal_type="lunch",
        food_name="Chicken Breast",
        quantity=1.0,
        unit="serving",
        calories=247.5,
        protein_g=46.5,
        carbs_g=0.0,
        fat_g=5.4,
        source="fatsecret",
        source_id="33691",
        raw_input="grilled chicken breast",
    )
    assert entry.meal_type == "lunch"
    assert entry.weight_g is None


def test_food_entry_create_invalid_meal_type():
    with pytest.raises(ValidationError):
        FoodEntryCreate(
            meal_type="brunch",
            food_name="Toast",
            quantity=1.0,
            unit="slice",
            calories=80.0,
            protein_g=3.0,
            carbs_g=14.0,
            fat_g=1.0,
            source="usda",
            raw_input="toast",
        )


def test_food_search_result():
    result = FoodSearchResult(
        food_id="33691",
        food_name="Chicken Breast",
        source="fatsecret",
        calories=165.0,
        protein_g=31.0,
        carbs_g=0.0,
        fat_g=3.6,
        serving_description="Per 100g",
    )
    assert result.source == "fatsecret"


def test_daily_summary():
    meal = MealSummary(
        meal_type="lunch",
        calories=500.0,
        protein_g=40.0,
        carbs_g=50.0,
        fat_g=15.0,
        entry_count=2,
    )
    summary = DailySummary(
        date=datetime.date(2026, 4, 15),
        meals=[meal],
        total_calories=500.0,
        total_protein_g=40.0,
        total_carbs_g=50.0,
        total_fat_g=15.0,
    )
    assert summary.total_calories == 500.0
    assert len(summary.meals) == 1
