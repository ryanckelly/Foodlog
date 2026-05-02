import datetime
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.api.routers.dashboard import (
    _background_health_sync,
    _sync_due,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="foodlog/templates")


def _parse_date(s: str | None) -> datetime.date:
    if not s:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return datetime.date.today()


@router.get("/timeline", response_class=HTMLResponse)
def timeline(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    date: str | None = None,
    focus: str | None = None,
) -> HTMLResponse:
    day = _parse_date(date)
    today = datetime.date.today()

    if _sync_due():
        background_tasks.add_task(_background_health_sync)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/timeline.html",
        context={
            "day": day,
            "today": today,
            "is_today": day == today,
            "focus": focus,
        },
    )
