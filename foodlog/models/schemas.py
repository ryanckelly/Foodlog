import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MealType(str, Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"


class FoodEntryCreate(BaseModel):
    meal_type: MealType
    food_name: str
    quantity: float = Field(gt=0)
    unit: str
    weight_g: float | None = None
    calories: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    fiber_g: float | None = None
    sugar_g: float | None = None
    sodium_mg: float | None = None
    source: str
    source_id: str | None = None
    raw_input: str
    logged_at: datetime.datetime | None = None


class FoodEntryUpdate(BaseModel):
    meal_type: MealType | None = None
    food_name: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    weight_g: float | None = None
    calories: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbs_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    source: str | None = None
    source_id: str | None = None


class FoodEntryResponse(BaseModel):
    id: int
    meal_type: str
    food_name: str
    quantity: float
    unit: str
    weight_g: float | None
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None
    sugar_g: float | None
    sodium_mg: float | None
    source: str
    source_id: str | None
    raw_input: str
    logged_at: datetime.datetime
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class FoodSearchResult(BaseModel):
    food_id: str
    food_name: str
    source: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    serving_description: str
    fiber_g: float | None = None
    sugar_g: float | None = None
    sodium_mg: float | None = None


class MealSummary(BaseModel):
    meal_type: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    entry_count: int


class DailySummary(BaseModel):
    date: datetime.date
    meals: list[MealSummary]
    total_calories: float
    total_protein_g: float
    total_carbs_g: float
    total_fat_g: float


class RangeSummary(BaseModel):
    start_date: datetime.date
    end_date: datetime.date
    days: int
    total_calories: float
    total_protein_g: float
    total_carbs_g: float
    total_fat_g: float
    avg_daily_calories: float
    avg_daily_protein_g: float
    avg_daily_carbs_g: float
    avg_daily_fat_g: float
