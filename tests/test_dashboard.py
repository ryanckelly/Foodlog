import base64
import datetime
import json
from unittest.mock import AsyncMock, patch

import itsdangerous
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from foodlog.config import settings
from foodlog.db.models import DailyActivity, GoogleOAuthToken


@pytest.fixture
def sso_enabled(monkeypatch):
    """Re-enable Google SSO configuration after the autouse fixture clears it."""
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "foodlog_session_secret_key", "test-session-secret")
    monkeypatch.setattr(settings, "foodlog_authorized_email", "owner@example.com")
    # foodlog_public_base_url is already set by _oauth_settings


def test_dashboard_index(client: TestClient):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "FoodLog" in response.text


def test_dashboard_index_redirects_to_login_when_sso_configured(raw_client: TestClient, sso_enabled):
    response = raw_client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/login"


def test_dashboard_feed_returns_401_when_sso_configured(raw_client: TestClient, sso_enabled):
    response = raw_client.get("/dashboard/feed", follow_redirects=False)
    assert response.status_code == 401
    assert "Unauthorized" in response.text


# ── Health integration tests ─────────────────────────────────────────────────

_HEALTH_SESSION_SECRET = "test-session"


def _make_session_cookie(data: dict) -> str:
    signer = itsdangerous.TimestampSigner(_HEALTH_SESSION_SECRET)
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


def _login_health(client, email="ryan.c.kelly@gmail.com"):
    client.cookies.set("session", _make_session_cookie({"user": email}))


def _configure_health(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "foodlog_authorized_email", "ryan.c.kelly@gmail.com")
    monkeypatch.setattr(settings, "foodlog_session_secret_key", _HEALTH_SESSION_SECRET)
    monkeypatch.setattr(settings, "foodlog_google_token_key", Fernet.generate_key().decode())


@pytest.fixture
def health_raw_client(monkeypatch, db_session):
    """raw_client variant that initializes the app AFTER health settings are applied.

    SessionMiddleware captures the secret_key at app-creation time, so we must
    patch settings before calling create_app() — not after.
    """
    from foodlog.api.app import create_app
    from foodlog.api.dependencies import get_db

    _configure_health(monkeypatch)

    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client


def test_feed_unconnected_shows_connect_prompt(health_raw_client):
    _login_health(health_raw_client)
    resp = health_raw_client.get("/dashboard/feed?date_range=today")
    assert resp.status_code == 200
    assert "Connect Google Health" in resp.text


def test_feed_connected_renders_movement_section(health_raw_client, db_session):
    _login_health(health_raw_client)

    fernet = Fernet(settings.foodlog_google_token_key.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    ))
    db_session.add(DailyActivity(
        date=datetime.date.today(),
        steps=8432,
        active_calories_kcal=512.0,
        source="watch",
        external_id="da-today",
    ))
    db_session.commit()

    from foodlog.services.health_sync import SyncResult
    with patch("foodlog.api.routers.dashboard._run_health_sync",
               new=AsyncMock(return_value=SyncResult(ok=True))):
        resp = health_raw_client.get("/dashboard/feed?date_range=today")

    assert resp.status_code == 200
    assert "Movement" in resp.text
    # Happy path: no stale / rate-limited banner text.
    assert "rate limited" not in resp.text
    assert "sync failed" not in resp.text


def test_feed_rate_limited_shows_rate_limited_banner(health_raw_client, db_session):
    _login_health(health_raw_client)

    fernet = Fernet(settings.foodlog_google_token_key.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    ))
    db_session.commit()

    from foodlog.services.health_sync import SyncResult
    with patch("foodlog.api.routers.dashboard._run_health_sync",
               new=AsyncMock(return_value=SyncResult(ok=False, rate_limited=True))):
        resp = health_raw_client.get("/dashboard/feed?date_range=today")

    assert resp.status_code == 200
    assert "rate limited" in resp.text.lower()


def test_feed_server_error_shows_stale_banner(health_raw_client, db_session):
    _login_health(health_raw_client)

    fernet = Fernet(settings.foodlog_google_token_key.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    ))
    db_session.commit()

    from foodlog.services.health_sync import SyncResult
    with patch("foodlog.api.routers.dashboard._run_health_sync",
               new=AsyncMock(return_value=SyncResult(ok=False, server_error=True))):
        resp = health_raw_client.get("/dashboard/feed?date_range=today")

    assert resp.status_code == 200
    assert "sync failed" in resp.text.lower()


def test_feed_old_token_triggers_opportunistic_reauth(health_raw_client, db_session):
    _login_health(health_raw_client)

    fernet = Fernet(settings.foodlog_google_token_key.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                   - datetime.timedelta(days=6),
    ))
    db_session.commit()

    resp = health_raw_client.get("/dashboard/feed?date_range=today")
    assert resp.headers.get("HX-Redirect") == "/health/connect"


def test_feed_invalid_grant_shows_reconnect_banner(health_raw_client, db_session):
    _login_health(health_raw_client)

    fernet = Fernet(settings.foodlog_google_token_key.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                   - datetime.timedelta(days=1),
    ))
    db_session.commit()

    from foodlog.services.google_token import TokenInvalid
    with patch("foodlog.api.routers.dashboard._run_health_sync",
               new=AsyncMock(side_effect=TokenInvalid("invalid_grant"))):
        resp = health_raw_client.get("/dashboard/feed?date_range=today")

    assert resp.status_code == 200
    assert "Reconnect" in resp.text or "reconnect" in resp.text
