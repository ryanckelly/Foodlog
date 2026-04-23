import pytest
from fastapi.testclient import TestClient

from foodlog.config import settings


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
