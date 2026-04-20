import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="foodlog/templates")

@router.get("", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard/index.html")

@router.get("/feed", response_class=HTMLResponse)
def feed_partial(
    request: Request,
    date_range: str = "today",
    db: Session = Depends(get_db)
):
    entry_svc = EntryService(db)
    summary_svc = SummaryService(db)
    
    today = datetime.date.today()
    if date_range == "yesterday":
        start_date = today - datetime.timedelta(days=1)
        end_date = start_date
    elif date_range == "week":
        start_date = today - datetime.timedelta(days=7)
        end_date = today
    else:
        start_date = today
        end_date = today
        
    if start_date == end_date:
        entries = entry_svc.get_by_date(start_date)
        summary = summary_svc.daily(start_date)
    else:
        entries = entry_svc.get_by_range(start_date, end_date)
        summary = summary_svc.range(start_date, end_date)
        
    return templates.TemplateResponse(
        request=request,
        name="dashboard/feed_partial.html", 
        context={
            "entries": entries, 
            "summary": summary
        }
    )