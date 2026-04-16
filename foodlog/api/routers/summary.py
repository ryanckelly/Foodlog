import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.models.schemas import DailySummary, RangeSummary
from foodlog.services.nutrition import SummaryService

router = APIRouter(prefix="/summary", tags=["summary"])


@router.get("/daily", response_model=DailySummary)
def daily_summary(
    date: datetime.date | None = None,
    db: Session = Depends(get_db),
):
    svc = SummaryService(db)
    return svc.daily(date or datetime.date.today())


@router.get("/range", response_model=RangeSummary)
def range_summary(
    start: datetime.date,
    end: datetime.date,
    db: Session = Depends(get_db),
):
    svc = SummaryService(db)
    return svc.range(start, end)
