import base64
import datetime
import json
from unittest.mock import patch, AsyncMock

import itsdangerous
import pytest
from cryptography.fernet import Fernet

from foodlog.config import settings
from foodlog.db.models import GoogleOAuthToken

_SESSION_SECRET = "test-session-secret"


@pytest.fixture(autouse=True)
def _google_health_settings(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "foodlog_authorized_email", "ryan.c.kelly@gmail.com")
    monkeypatch.setattr(settings, "foodlog_session_secret_key", _SESSION_SECRET)
    monkeypatch.setattr(settings, "foodlog_google_token_key", Fernet.generate_key().decode())


OAUTH_STATE = "test-state-xyz"


def _make_session_cookie(data: dict) -> str:
    """Build a signed Starlette session cookie identical to what SessionMiddleware produces."""
    signer = itsdangerous.TimestampSigner(_SESSION_SECRET)
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


def _login(raw_client, email="ryan.c.kelly@gmail.com", with_state: bool = True):
    """Seed a signed session cookie into the TestClient's cookie jar."""
    data: dict = {"user": email}
    if with_state:
        data["health_oauth_state"] = OAUTH_STATE
    raw_client.cookies.set("session", _make_session_cookie(data))


def test_connect_without_session_redirects_to_login(raw_client):
    resp = raw_client.get("/health/connect", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].endswith("/login")


def test_connect_with_session_redirects_to_google(raw_client):
    _login(raw_client)
    resp = raw_client.get("/health/connect", follow_redirects=False)
    assert resp.status_code in (302, 307)
    loc = resp.headers["location"]
    assert loc.startswith("https://accounts.google.com/")
    assert "access_type=offline" in loc
    assert "googlehealth.activity_and_fitness.readonly" in loc


def test_callback_rejects_when_not_logged_in(raw_client):
    resp = raw_client.get("/health/connect/callback?code=abc&state=xyz", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].endswith("/login")


def test_callback_rejects_email_mismatch(raw_client, db_session):
    _login(raw_client, email="someone-else@gmail.com")
    with patch("foodlog.api.routers.health_oauth._exchange_code", new=AsyncMock(
        return_value={"refresh_token": "r", "access_token": "a", "expires_in": 3600,
                       "scope": "x", "id_token_email": "intruder@gmail.com"}
    )):
        resp = raw_client.get(
            f"/health/connect/callback?code=abc&state={OAUTH_STATE}",
            follow_redirects=False,
        )
    # email mismatch is only checked once state check passes; the email
    # from the fixture intentionally doesn't match authorized_email.
    assert resp.status_code in (302, 307, 403)
    # Regardless of which gate caught it, no token should have been written.
    assert db_session.query(GoogleOAuthToken).count() == 0


def test_callback_stores_encrypted_token(raw_client, db_session):
    _login(raw_client)
    with patch("foodlog.api.routers.health_oauth._exchange_code", new=AsyncMock(
        return_value={
            "refresh_token": "refresh-xyz",
            "access_token": "a",
            "expires_in": 3600,
            "scope": "openid email profile googlehealth.sleep.readonly",
            "id_token_email": "ryan.c.kelly@gmail.com",
        }
    )):
        resp = raw_client.get(
            f"/health/connect/callback?code=abc&state={OAUTH_STATE}",
            follow_redirects=False,
        )
    assert resp.status_code in (302, 307)
    row = db_session.query(GoogleOAuthToken).one()
    assert row.id == 1
    assert "refresh-xyz" not in row.refresh_token_encrypted  # encrypted


def test_callback_rejects_bad_state(raw_client):
    _login(raw_client, with_state=True)
    resp = raw_client.get(
        "/health/connect/callback?code=abc&state=wrong-state",
        follow_redirects=False,
    )
    assert resp.status_code == 400
