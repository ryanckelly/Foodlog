import datetime
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.api.routers.dashboard import (
    _background_health_sync,
    _sync_due,
)
from foodlog.config import settings

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


def _pct(value: int, lo: int, hi: int) -> float:
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))


def _is_focused(focus: str | None, start: datetime.datetime, end: datetime.datetime) -> bool:
    if not focus:
        return False
    try:
        a, b = focus.split("-")
        ah, am = (int(x) for x in a.split(":"))
        bh, bm = (int(x) for x in b.split(":"))
    except (ValueError, AttributeError):
        return False
    return (start.hour == ah and start.minute == am
            and end.hour == bh and end.minute == bm)


@router.get("/timeline", response_class=HTMLResponse)
def timeline(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    date: str | None = None,
    focus: str | None = None,
):
    if settings.google_sso_configured and "user" not in request.session:
        return RedirectResponse(url="/login")

    from foodlog.db.models import IntervalHeartRate
    day = _parse_date(date)
    today = datetime.date.today()

    if _sync_due():
        background_tasks.add_task(_background_health_sync)

    start_dt = datetime.datetime.combine(day, datetime.time.min)
    end_dt = start_dt + datetime.timedelta(days=1)

    hr_rows = db.query(IntervalHeartRate).filter(
        IntervalHeartRate.start_at >= start_dt,
        IntervalHeartRate.start_at < end_dt,
    ).all()
    HR_MIN, HR_MAX = 40, 180
    hr_slots: list[dict | None] = [None] * 96
    for r in hr_rows:
        idx = (r.start_at.hour * 60 + r.start_at.minute) // 15
        if 0 <= idx < 96:
            hr_slots[idx] = {
                "avg": r.bpm_avg,
                "min": r.bpm_min,
                "max": r.bpm_max,
                "avg_pct":   _pct(r.bpm_avg, HR_MIN, HR_MAX),
                "range_bottom_pct": _pct(r.bpm_min, HR_MIN, HR_MAX),
                "range_height_pct": _pct(r.bpm_max, HR_MIN, HR_MAX) - _pct(r.bpm_min, HR_MIN, HR_MAX),
            }

    from foodlog.db.models import IntervalActivity

    activity_rows = db.query(IntervalActivity).filter(
        IntervalActivity.start_at >= start_dt,
        IntervalActivity.start_at < end_dt,
    ).all()
    steps_slots: list[int | None]   = [None] * 96
    dist_slots:  list[float | None] = [None] * 96
    floors_slots: list[int | None]  = [None] * 96
    for r in activity_rows:
        idx = (r.start_at.hour * 60 + r.start_at.minute) // 15
        if 0 <= idx < 96:
            steps_slots[idx]  = r.steps
            dist_slots[idx]   = r.distance_m
            floors_slots[idx] = r.floors

    def _scale(slots):
        nonempty = [v for v in slots if v not in (None, 0)]
        peak = max(nonempty) if nonempty else 1
        return [
            (None if v is None else (v / peak * 100.0))
            for v in slots
        ]

    steps_pct  = _scale(steps_slots)
    dist_pct   = _scale(dist_slots)
    floors_pct = _scale(floors_slots)

    from foodlog.db.models import IntervalAzm

    azm_rows = db.query(IntervalAzm).filter(
        IntervalAzm.start_at >= start_dt,
        IntervalAzm.start_at < end_dt,
    ).all()
    azm_slots: list[dict | None] = [None] * 96
    for r in azm_rows:
        idx = (r.start_at.hour * 60 + r.start_at.minute) // 15
        if 0 <= idx < 96:
            azm_slots[idx] = {
                "fat_burn": r.fat_burn_min or 0,
                "cardio":   r.cardio_min or 0,
                "peak":     r.peak_min or 0,
            }
    azm_peak_total = max(
        (s["fat_burn"] + s["cardio"] + s["peak"]) for s in azm_slots if s is not None
    ) if any(azm_slots) else 1
    for s in azm_slots:
        if s is None:
            continue
        s["fb_pct"] = (s["fat_burn"] / azm_peak_total * 100.0) if azm_peak_total else 0
        s["ca_pct"] = (s["cardio"]   / azm_peak_total * 100.0) if azm_peak_total else 0
        s["pk_pct"] = (s["peak"]     / azm_peak_total * 100.0) if azm_peak_total else 0

    from foodlog.db.models import Workout, FoodEntry

    def _pct_of_day(dt: datetime.datetime) -> float:
        secs = (dt - start_dt).total_seconds()
        return max(0.0, min(100.0, secs / 86400.0 * 100.0))

    workouts = db.query(Workout).filter(
        Workout.start_at >= start_dt,
        Workout.start_at < end_dt,
    ).all()
    workout_views = []
    for w in workouts:
        left = _pct_of_day(w.start_at)
        right = 100.0 - _pct_of_day(w.end_at)
        workout_views.append({
            "label": w.activity_type,
            "duration_min": w.duration_min,
            "left_pct":  left,
            "right_pct": right,
            "start_hhmm": w.start_at.strftime("%H:%M"),
            "end_hhmm":   w.end_at.strftime("%H:%M"),
            "is_focused": _is_focused(focus, w.start_at, w.end_at),
        })

    meals = db.query(FoodEntry).filter(
        FoodEntry.logged_at >= start_dt,
        FoodEntry.logged_at < end_dt,
    ).all()
    meal_views = [
        {
            "name": m.food_name,
            "meal_type": m.meal_type,
            "left_pct": _pct_of_day(m.logged_at),
        }
        for m in meals
    ]

    has_data = (
        any(s is not None for s in hr_slots)
        or any(s is not None for s in steps_slots)
        or any(s is not None for s in dist_slots)
        or any(s is not None for s in floors_slots)
        or any(s is not None for s in azm_slots)
        or bool(workout_views)
        or bool(meal_views)
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard/timeline.html",
        context={
            "day": day,
            "today": today,
            "is_today": day == today,
            "focus": focus,
            "has_data": has_data,
            "hr_slots": hr_slots,
            "steps_slots": steps_slots,
            "dist_slots": dist_slots,
            "floors_slots": floors_slots,
            "steps_pct": steps_pct,
            "dist_pct": dist_pct,
            "floors_pct": floors_pct,
            "azm_slots": azm_slots,
            "workout_views": workout_views,
            "meal_views": meal_views,
            "one_day": datetime.timedelta(days=1),
        },
    )
