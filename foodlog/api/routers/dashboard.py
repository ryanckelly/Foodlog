import datetime
import logging
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db, get_session_factory_cached
from foodlog.clients.google_health import GoogleHealthClient
from foodlog.config import settings
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    DailyHrv,
    DailyRespiratoryOxygen,
    DailySleepTemperature,
    GoogleOAuthToken,
    RestingHeartRate,
    SleepSession,
    Workout,
)
from foodlog.services.google_token import GoogleTokenService, TokenInvalid, TokenMissing
from foodlog.services.health_sync import HealthSyncService, SyncResult
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="foodlog/templates")

REAUTH_AGE_DAYS = 5  # spec: opportunistic re-auth before Google's 7-day wall
SYNC_MIN_INTERVAL_S = 30  # cap how often we hit Google from background sync


# Module-level state for the background-sync model.
#
# Pre-2026-04-25 the dashboard ran a full Google Health sync inline on every
# /dashboard/feed render — 1 token mint + 6 sequential Google API calls,
# adding ~5s of "Loading…" on every page load (and on every date-range
# toggle). The page now renders straight from the DB and schedules the
# sync as a FastAPI BackgroundTask so the request never blocks on Google.
# Banner state (stale / rate-limited / reconnect) reflects the most recent
# sync attempt rather than the current one.
@dataclass
class _SyncState:
    last_at: datetime.datetime | None = None
    inflight: bool = False
    last_ok: bool = True
    rate_limited: bool = False
    server_error: bool = False
    reconnect_needed: bool = False

    def reset(self) -> None:
        self.last_at = None
        self.inflight = False
        self.last_ok = True
        self.rate_limited = False
        self.server_error = False
        self.reconnect_needed = False


_sync_state = _SyncState()


async def _run_health_sync(db: Session) -> SyncResult:
    """Trigger on-presence sync. Raises TokenInvalid or TokenMissing on auth failure.

    Returns a SyncResult so the caller can distinguish partial failures
    (rate-limited vs server-error) for UI banner copy.
    """
    token_svc = GoogleTokenService(db)
    async with httpx.AsyncClient(timeout=15.0) as http:
        access = await token_svc.mint_access_token(http)
        client = GoogleHealthClient(http, access_token=access.value)
        sync = HealthSyncService(db, client)
        return await sync.sync_all()


def _sync_due() -> bool:
    if _sync_state.inflight:
        return False
    if _sync_state.last_at is None:
        return True
    age_s = (
        datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - _sync_state.last_at
    ).total_seconds()
    return age_s >= SYNC_MIN_INTERVAL_S


async def _background_health_sync() -> None:
    """Run a sync with its own DB session and update _sync_state.

    Scheduled via BackgroundTasks so it runs after the response is sent —
    the dashboard render never blocks on Google.
    """
    if _sync_state.inflight:
        return
    _sync_state.inflight = True
    try:
        factory = get_session_factory_cached()
        db = factory()
        try:
            try:
                result = await _run_health_sync(db)
                _sync_state.last_ok = result.ok
                _sync_state.rate_limited = result.rate_limited
                _sync_state.server_error = result.server_error
                _sync_state.reconnect_needed = False
            except (TokenInvalid, TokenMissing):
                _sync_state.last_ok = False
                _sync_state.rate_limited = False
                _sync_state.server_error = False
                _sync_state.reconnect_needed = True
            except Exception:
                logger.exception("background health sync crashed")
                _sync_state.last_ok = False
                _sync_state.rate_limited = False
                _sync_state.server_error = True
                _sync_state.reconnect_needed = False
        finally:
            db.close()
        _sync_state.last_at = (
            datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        )
    finally:
        _sync_state.inflight = False


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
            "start_at_date": w.start_at.date().isoformat(),
            "start_hhmm":    w.start_at.strftime("%H:%M"),
            "end_hhmm":      w.end_at.strftime("%H:%M"),
        })

    sleep = (db.query(SleepSession)
               .filter(SleepSession.start_at >= start_dt,
                       SleepSession.start_at < end_dt)
               .order_by(SleepSession.start_at.desc()).first())
    resting = (db.query(RestingHeartRate)
                 .filter(RestingHeartRate.measured_at >= start_dt,
                         RestingHeartRate.measured_at < end_dt)
                 .order_by(RestingHeartRate.measured_at.desc()).first())
    # Overnight-recovery metrics (all keyed by civil date, ~60-67% nightly
    # coverage on Pixel Watch). Each is the most recent row in the period — we
    # surface them on the sleep card as "last night" alongside the session.
    # Pure local reads; nothing here hits Google (see render-path contract).
    hrv = (db.query(DailyHrv)
             .filter(DailyHrv.date >= start_date, DailyHrv.date <= end_date)
             .order_by(DailyHrv.date.desc()).first())
    ro = (db.query(DailyRespiratoryOxygen)
            .filter(DailyRespiratoryOxygen.date >= start_date,
                    DailyRespiratoryOxygen.date <= end_date)
            .order_by(DailyRespiratoryOxygen.date.desc()).first())
    temp = (db.query(DailySleepTemperature)
              .filter(DailySleepTemperature.date >= start_date,
                      DailySleepTemperature.date <= end_date)
              .order_by(DailySleepTemperature.date.desc()).first())

    sleep_view = None
    if sleep is not None:
        # Skin-temp "unusual night" signal. relative_stddev_30d_c is the user's
        # 30-day stddev (≈constant ~0.8 C in practice — it is NOT the per-night
        # deviation, despite the field name), so the actual z-score is
        # (nightly - baseline) / stddev. |z| >= 2 flags illness/alcohol.
        temp_z = None
        if (temp is not None and temp.nightly_temp_c is not None
                and temp.baseline_temp_c is not None
                and temp.relative_stddev_30d_c):
            temp_z = (temp.nightly_temp_c - temp.baseline_temp_c) / temp.relative_stddev_30d_c
        sleep_view = {
            "duration_min": sleep.duration_min,
            "resting_hr": resting.bpm if resting else None,
            "deep_min": sleep.deep_min,
            "light_min": sleep.light_min,
            "rem_min": sleep.rem_min,
            "awake_min": sleep.awake_min,
            "asleep_min": sleep.asleep_min,
            "avg_hrv_ms": hrv.avg_hrv_ms if hrv else None,
            "breaths_per_min": ro.breaths_per_min if ro else None,
            "spo2_avg_pct": ro.spo2_avg_pct if ro else None,
            "spo2_low_pct": ro.spo2_low_pct if ro else None,
            "skin_temp_delta_c": (temp.nightly_temp_c - temp.baseline_temp_c)
                                 if temp_z is not None else None,
            "skin_temp_unusual": temp_z is not None and abs(temp_z) >= 2,
        }

    # `body_composition` holds Google Health weight points and body-fat points
    # as separate rows (different external_id, same measured_at on a barefoot
    # Renpho weigh-in). Filter to weight rows so a tied or newer body-fat row
    # can't outrank the actual weight reading and silently hide the card.
    # Then look up the body-fat row at the same instant to keep the % on the
    # card. See foodlog-bbl.
    latest_body = (db.query(BodyComposition)
                     .filter(BodyComposition.weight_kg.isnot(None))
                     .order_by(BodyComposition.measured_at.desc()).first())
    weight_view = None
    if latest_body is not None:
        week_ago = (db.query(BodyComposition)
                      .filter(BodyComposition.weight_kg.isnot(None),
                              BodyComposition.measured_at <= latest_body.measured_at
                                                            - datetime.timedelta(days=7))
                      .order_by(BodyComposition.measured_at.desc()).first())
        delta = None
        if week_ago is not None:
            delta = latest_body.weight_kg - week_ago.weight_kg
        body_fat_pct = latest_body.body_fat_pct
        if body_fat_pct is None:
            sibling_fat = (db.query(BodyComposition)
                             .filter(BodyComposition.measured_at == latest_body.measured_at,
                                     BodyComposition.body_fat_pct.isnot(None))
                             .first())
            if sibling_fat is not None:
                body_fat_pct = sibling_fat.body_fat_pct
        weight_view = {
            "weight_kg": latest_body.weight_kg,
            "delta_kg": delta,
            "body_fat_pct": body_fat_pct,
        }

    activity = (db.query(DailyActivity)
                  .filter(DailyActivity.date >= start_date,
                          DailyActivity.date <= end_date).all())
    # active_calories_kcal holds TOTAL daily expenditure (misnomer, see efy.6) —
    # that's the correct figure for net energy balance below. active_energy_kcal
    # is the real activity-only burn we now surface separately on the card.
    total_burned = sum(a.active_calories_kcal for a in activity) if activity else None
    active_energy = (sum(a.active_energy_kcal for a in activity if a.active_energy_kcal is not None)
                     if activity else None) or None
    total_steps = sum(a.steps for a in activity) if activity else 0
    # Steps "card" shows when there's activity for the period. Distinct from
    # the net-calories pill in the summary strip (which is aggregate).
    activity_view = None
    if activity:
        activity_view = {
            "steps": total_steps,
            "calories_kcal": total_burned or 0,
            "active_energy_kcal": active_energy,
        }
    return {
        "workouts": workout_views,
        "sleep": sleep_view,
        "weight": weight_view,
        "activity": activity_view,
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
    background_tasks: BackgroundTasks,
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

    entries.sort(key=lambda x: x.effective_at, reverse=True)

    def _same_batch(entry, group) -> bool:
        # Exact grouping when both rows carry a submission_id (post foodlog-b1f);
        # otherwise fall back to the legacy 5-minute same-meal time-window cluster.
        if entry.submission_id and group["submission_id"]:
            return entry.submission_id == group["submission_id"]
        time_diff = abs((entry.effective_at - group["logged_at"]).total_seconds())
        return entry.meal_type == group["meal_type"] and time_diff < 300

    grouped_entries = []
    if entries:
        current_group = {
            "meal_type": entries[0].meal_type,
            "submission_id": entries[0].submission_id,
            "logged_at": entries[0].effective_at,
            "entries": [entries[0]],
            "total_calories": entries[0].calories,
            "total_protein_g": entries[0].protein_g,
            "total_carbs_g": entries[0].carbs_g,
            "total_fat_g": entries[0].fat_g,
        }
        for entry in entries[1:]:
            if _same_batch(entry, current_group):
                current_group["entries"].append(entry)
                current_group["total_calories"] += entry.calories
                current_group["total_protein_g"] += entry.protein_g
                current_group["total_carbs_g"] += entry.carbs_g
                current_group["total_fat_g"] += entry.fat_g
            else:
                grouped_entries.append(current_group)
                current_group = {
                    "meal_type": entry.meal_type,
                    "submission_id": entry.submission_id,
                    "logged_at": entry.effective_at,
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

    # Render movement straight from the DB. The Google sync is fire-and-forget
    # via BackgroundTasks (see _background_health_sync) so the request never
    # blocks on Google. Banners reflect the most recent completed sync — they
    # lag the in-flight sync by one cycle, which is a deliberate trade for the
    # render-path speedup. See module docstring on _SyncState.
    reconnect_needed = False
    stale = False
    rate_limited = False
    include_movement = False
    movement_ctx = {}
    if settings.google_health_configured and _is_connected(db):
        include_movement = True
        movement_ctx = _build_movement_context(db, start_date, end_date)
        reconnect_needed = _sync_state.reconnect_needed
        if not _sync_state.last_ok and not reconnect_needed:
            stale = True
            rate_limited = _sync_state.rate_limited
        if _sync_due():
            background_tasks.add_task(_background_health_sync)

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
            "rate_limited": rate_limited,
            "net_calories": net_calories,
            **movement_ctx,
        },
        # Tell Cloudflare / upstream proxies NOT to rewrite or minify the body.
        # CF Auto Minify was silently dropping the Movement & Recovery partial
        # when it ran on this endpoint's HTML.
        headers={"Cache-Control": "private, no-store, no-transform"},
    )
