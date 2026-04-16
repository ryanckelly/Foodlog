import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from foodlog.db.models import Base, FoodEntry


def test_create_food_entry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        entry = FoodEntry(
            meal_type="lunch",
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
        session.add(entry)
        session.commit()
        session.refresh(entry)

        assert entry.id is not None
        assert entry.food_name == "Chicken Breast"
        assert entry.calories == 247.5
        assert entry.logged_at is not None
        assert entry.created_at is not None


def test_nullable_fields():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        entry = FoodEntry(
            meal_type="snack",
            food_name="Apple",
            quantity=1.0,
            unit="medium",
            calories=95.0,
            protein_g=0.5,
            carbs_g=25.0,
            fat_g=0.3,
            source="usda",
            source_id="171688",
            raw_input="an apple",
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)

        assert entry.weight_g is None
        assert entry.fiber_g is None
        assert entry.sugar_g is None
        assert entry.sodium_mg is None
