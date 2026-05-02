from fastapi.templating import Jinja2Templates
from fastapi import Request
from starlette.datastructures import Headers

TEMPLATES = Jinja2Templates(directory="foodlog/templates")


def _fake_request():
    scope = {"type": "http", "headers": Headers().raw, "method": "GET", "path": "/"}
    return Request(scope)


def test_movement_partial_empty_state_renders():
    html = TEMPLATES.get_template("dashboard/movement_partial.html").render(
        workouts=[],
        sleep=None,
        weight=None,
        net_calories=None,
    )
    assert "Movement" in html
    assert "No movement or recovery data" in html


def test_movement_partial_renders_workout_card():
    html = TEMPLATES.get_template("dashboard/movement_partial.html").render(
        workouts=[{
            "activity_type": "Run",
            "distance_km": 6.8,
            "duration_min": 42,
            "calories_kcal": 410,
            "avg_hr": 152,
            "max_hr": 174,
            "hr_samples": [{"pct": 30}, {"pct": 55}, {"pct": 95}],
        }],
        sleep={"duration_min": 387, "resting_hr": 58},
        weight={"weight_kg": 81.4, "delta_kg": -0.3, "body_fat_pct": 19.2},
        net_calories=None,
    )
    assert "Run" in html
    assert "6.8" in html
    assert "42" in html
    assert "6h 27m" in html  # 387 min formatted
    assert "81.4" in html


def test_health_connect_page_renders_prompt():
    html = TEMPLATES.get_template("dashboard/health_connect.html").render()
    assert "Connect Google Health" in html
    assert '/health/connect' in html


def test_workout_card_has_timeline_deep_link(db_session, monkeypatch):
    import datetime
    from fastapi.testclient import TestClient
    from foodlog.api.app import create_app
    from foodlog.db.models import Workout, GoogleOAuthToken
    from foodlog.config import settings
    from cryptography.fernet import Fernet

    # Enable google health so movement section is rendered
    _KEY = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "foodlog_google_token_key", _KEY)

    fernet = Fernet(_KEY.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    ))

    today = datetime.date.today()
    start = datetime.datetime.combine(today, datetime.time(12, 0))
    end = datetime.datetime.combine(today, datetime.time(12, 47))
    db_session.add(Workout(
        external_id="walk-3",
        start_at=start,
        end_at=end,
        activity_type="Walk", duration_min=47,
        calories_kcal=300.0, distance_m=3500.0,
        avg_hr=112, max_hr=145, source="FITBIT",
    ))
    db_session.commit()

    # Seed recent sync to suppress background task and avoid token errors
    from foodlog.api.routers import dashboard as dm
    dm._sync_state.last_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    client = TestClient(create_app())
    r = client.get("/dashboard/feed?date_range=today")
    assert r.status_code == 200
    # The link points to the timeline with the right deep-link params
    assert f"/dashboard/timeline?date={today.isoformat()}" in r.text
    assert "focus=12:00-12:47" in r.text
    # The visible affordance text
    assert "→ Timeline" in r.text
