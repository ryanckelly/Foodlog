import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from foodlog.db.models import FoodEntry
from foodlog.models.schemas import DailySummary, MealSummary, RangeSummary


class SummaryService:
    def __init__(self, session: Session):
        self.session = session

    def daily(self, date: datetime.date) -> DailySummary:
        rows = (
            self.session.query(
                FoodEntry.meal_type,
                func.sum(FoodEntry.calories).label("calories"),
                func.sum(FoodEntry.protein_g).label("protein_g"),
                func.sum(FoodEntry.carbs_g).label("carbs_g"),
                func.sum(FoodEntry.fat_g).label("fat_g"),
                func.count(FoodEntry.id).label("entry_count"),
            )
            .filter(func.date(FoodEntry.logged_at) == date)
            .group_by(FoodEntry.meal_type)
            .all()
        )

        meals = [
            MealSummary(
                meal_type=row.meal_type,
                calories=row.calories,
                protein_g=row.protein_g,
                carbs_g=row.carbs_g,
                fat_g=row.fat_g,
                entry_count=row.entry_count,
            )
            for row in rows
        ]

        return DailySummary(
            date=date,
            meals=meals,
            total_calories=sum(m.calories for m in meals),
            total_protein_g=sum(m.protein_g for m in meals),
            total_carbs_g=sum(m.carbs_g for m in meals),
            total_fat_g=sum(m.fat_g for m in meals),
        )

    def range(self, start: datetime.date, end: datetime.date) -> RangeSummary:
        row = (
            self.session.query(
                func.sum(FoodEntry.calories).label("calories"),
                func.sum(FoodEntry.protein_g).label("protein_g"),
                func.sum(FoodEntry.carbs_g).label("carbs_g"),
                func.sum(FoodEntry.fat_g).label("fat_g"),
            )
            .filter(func.date(FoodEntry.logged_at).between(start, end))
            .one()
        )

        days = (end - start).days + 1
        total_cal = row.calories or 0.0
        total_pro = row.protein_g or 0.0
        total_carb = row.carbs_g or 0.0
        total_fat = row.fat_g or 0.0

        return RangeSummary(
            start_date=start,
            end_date=end,
            days=days,
            total_calories=total_cal,
            total_protein_g=total_pro,
            total_carbs_g=total_carb,
            total_fat_g=total_fat,
            avg_daily_calories=total_cal / days,
            avg_daily_protein_g=total_pro / days,
            avg_daily_carbs_g=total_carb / days,
            avg_daily_fat_g=total_fat / days,
        )
