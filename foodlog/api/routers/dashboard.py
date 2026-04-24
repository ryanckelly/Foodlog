import datetime

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.clients.google_health import GoogleHealthClient
from foodlog.config import settings
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    GoogleOAuthToken,
    RestingHeartRate,
    SleepSession,
    Workout,
)
from foodlog.services.google_token import GoogleTokenService, TokenInvalid, TokenMissing
from foodlog.services.health_sync import HealthSyncService
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="foodlog/templates")

REAUTH_AGE_DAYS = 5  # spec: opportunistic re-auth before Google's 7-day wall


async def _run_health_sync(db: Session) -> None:
    """Trigger on-presence sync. Raises TokenInvalid or TokenMissing on auth failure."""
    token_svc = GoogleTokenService(db)
    async with httpx.AsyncClient(timeout=15.0) as http:
        access = await token_svc.mint_access_token(http)
        client = GoogleHealthClient(http, access_token=access.value)
        sync = HealthSyncService(db, client)
        await sync.sync_all()


def _is_connected(db: Session) -> bool:
    return db.get(GoogleOAuthToken, 1) is not None


def _token_is_aging(db: Session) -> bool:
    try:
        return GoogleTokenService(db).token_age_days() > REAUTH_AGE_DAYS
    except TokenMissing:
        return False


def _build_movement_context(db: Session, start_date, end_date) -> dict:
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date + datetime.timedelta(days=1), datetime.time.min)

    workouts = (db.query(Workout)
                  .filter(Workout.start_at >= start_dt, Workout.start_at < end_dt)
                  .order_by(Workout.start_at.desc()).all())
    workout_views = []
    for w in workouts:
        samples = w.hr_samples
        if samples and w.max_hr:
            peak = max(w.max_hr, max(s.bpm for s in samples))
            bars = [{"pct": round(s.bpm / peak * 100)} for s in samples]
        else:
            bars = []
        workout_views.append({
            "activity_type": w.activity_type.title(),
            "distance_km": round(w.distance_m / 1000, 1) if w.distance_m else None,
            "duration_min": w.duration_min,
            "calories_kcal": w.calories_kcal,
            "avg_hr": w.avg_hr,
            "max_hr": w.max_hr,
            "hr_samples": bars,
        })

    sleep = (db.query(SleepSession)
               .filter(SleepSession.start_at >= start_dt,
                       SleepSession.start_at < end_dt)
               .order_by(SleepSession.start_at.desc()).first())
    resting = (db.query(RestingHeartRate)
                 .filter(RestingHeartRate.measured_at >= start_dt,
                         RestingHeartRate.measured_at < end_dt)
                 .order_by(RestingHeartRate.measured_at.desc()).first())
    sleep_view = None
    if sleep is not None:
        sleep_view = {
            "duration_min": sleep.duration_min,
            "resting_hr": resting.bpm if resting else None,
        }

    latest_body = (db.query(BodyComposition)
                     .order_by(BodyComposition.measured_at.desc()).first())
    weight_view = None
    if latest_body and latest_body.weight_kg:
        week_ago = (db.query(BodyComposition)
                      .filter(BodyComposition.measured_at <= latest_body.measured_at
                                                            - datetime.timedelta(days=7))
                      .order_by(BodyComposition.measured_at.desc()).first())
        delta = None
        if week_ago and week_ago.weight_kg:
            delta = latest_body.weight_kg - week_ago.weight_kg
        weight_view = {
            "weight_kg": latest_body.weight_kg,
            "delta_kg": delta,
            "body_fat_pct": latest_body.body_fat_pct,
        }

    activity = (db.query(DailyActivity)
                  .filter(DailyActivity.date >= start_date,
                          DailyActivity.date <= end_date).all())
    total_burned = sum(a.active_calories_kcal for a in activity) if activity else None
    return {
        "workouts": workout_views,
        "sleep": sleep_view,
        "weight": weight_view,
        "total_burned": total_burned,
    }


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
async def feed_partial(
    request: Request,
    date_range: str = "today",
    db: Session = Depends(get_db),
):
    # SSO guard (preserved from pre-existing behavior).
    if settings.google_sso_configured and "user" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    # If health is configured but not connected, render the connect prompt
    # instead of the feed.
    if settings.google_health_configured and not _is_connected(db):
        return templates.TemplateResponse(
            request=request, name="dashboard/health_connect.html", context={}
        )

    # Opportunistic re-auth: if the refresh token is older than 5 days,
    # redirect (via HX-Redirect) through /health/connect before the 7-day
    # wall bites. Google usually fulfills this silently.
    if settings.google_health_configured and _is_connected(db) and _token_is_aging(db):
        return HTMLResponse("", headers={"HX-Redirect": "/health/connect"})

    # Meals (unchanged from original)
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

    # Health sync (on-presence)
    reconnect_needed = False
    stale = False
    include_movement = False
    movement_ctx = {}
    if settings.google_health_configured and _is_connected(db):
        try:
            await _run_health_sync(db)
            include_movement = True
        except (TokenInvalid, TokenMissing):
            reconnect_needed = True
        except Exception:
            stale = True
            include_movement = True  # render whatever's in the DB
        if include_movement:
            movement_ctx = _build_movement_context(db, start_date, end_date)

    net_calories = None
    if include_movement and movement_ctx.get("total_burned"):
        net_calories = (summary.total_calories or 0) - movement_ctx["total_burned"]

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
            "include_movement": include_movement,
            "reconnect_needed": reconnect_needed,
            "stale": stale,
            "net_calories": net_calories,
            **movement_ctx,
        },
    )
