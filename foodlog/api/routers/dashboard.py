import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates

from foodlog.api.dependencies import get_db
from foodlog.config import settings
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="foodlog/templates")


@router.get("", response_class=HTMLResponse)
def index(request: Request):
    if settings.google_sso_configured and "user" not in request.session:
        return RedirectResponse(url="/login")

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={"today": datetime.date.today()},
    )


@router.get("/feed", response_class=HTMLResponse)
def feed_partial(
    request: Request,
    date_range: str = "today",
    db: Session = Depends(get_db),
):
    if settings.google_sso_configured and "user" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    entry_svc = EntryService(db)
    summary_svc = SummaryService(db)

    today = datetime.date.today()
    if date_range == "yesterday":
        start_date = today - datetime.timedelta(days=1)
        end_date = start_date
        range_label = "yesterday"
    elif date_range == "week":
        start_date = today - datetime.timedelta(days=7)
        end_date = today
        range_label = "the past seven days"
    else:
        start_date = today
        end_date = today
        range_label = "today"

    if start_date == end_date:
        entries = entry_svc.get_by_date(start_date)
        summary = summary_svc.daily(start_date)
    else:
        entries = entry_svc.get_by_range(start_date, end_date)
        summary = summary_svc.range(start_date, end_date)

    entries.sort(key=lambda x: x.logged_at, reverse=True)

    grouped_entries = []
    if entries:
        current_group = {
            "meal_type": entries[0].meal_type,
            "logged_at": entries[0].logged_at,
            "entries": [entries[0]],
            "total_calories": entries[0].calories,
            "total_protein_g": entries[0].protein_g,
            "total_carbs_g": entries[0].carbs_g,
            "total_fat_g": entries[0].fat_g,
        }
        for entry in entries[1:]:
            time_diff = abs((entry.logged_at - current_group["logged_at"]).total_seconds())
            if entry.meal_type == current_group["meal_type"] and time_diff < 300:
                current_group["entries"].append(entry)
                current_group["total_calories"] += entry.calories
                current_group["total_protein_g"] += entry.protein_g
                current_group["total_carbs_g"] += entry.carbs_g
                current_group["total_fat_g"] += entry.fat_g
            else:
                grouped_entries.append(current_group)
                current_group = {
                    "meal_type": entry.meal_type,
                    "logged_at": entry.logged_at,
                    "entries": [entry],
                    "total_calories": entry.calories,
                    "total_protein_g": entry.protein_g,
                    "total_carbs_g": entry.carbs_g,
                    "total_fat_g": entry.fat_g,
                }
        grouped_entries.append(current_group)

    p_kcal = (summary.total_protein_g or 0) * 4
    c_kcal = (summary.total_carbs_g or 0) * 4
    f_kcal = (summary.total_fat_g or 0) * 9
    macro_kcal = p_kcal + c_kcal + f_kcal
    if macro_kcal > 0:
        p_pct = round(p_kcal / macro_kcal * 100)
        c_pct = round(c_kcal / macro_kcal * 100)
        f_pct = max(0, 100 - p_pct - c_pct)
    else:
        p_pct = c_pct = f_pct = 0

    entry_count = sum(len(g["entries"]) for g in grouped_entries)
    course_count = len(grouped_entries)

    return templates.TemplateResponse(
        request=request,
        name="dashboard/feed_partial.html",
        context={
            "grouped_entries": grouped_entries,
            "summary": summary,
            "range_label": range_label,
            "macro_pct": {"p": p_pct, "c": c_pct, "f": f_pct},
            "entry_count": entry_count,
            "course_count": course_count,
        },
    )
