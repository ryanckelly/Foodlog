import base64
import datetime
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from foodlog.db.models import OAuthPendingAuthorization
from foodlog.services.oauth import FOODLOG_SCOPES, FoodLogOAuthProvider, utcnow
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _client(client_id: str = "client_test") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl("https://claude.ai/api/mcp/auth_callback")],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=" ".join(FOODLOG_SCOPES),
        client_name="Claude",
        client_id_issued_at=1_700_000_000,
    )


async def _create_pending_authorization(
    provider: FoodLogOAuthProvider, client_id: str, state: str
) -> str:
    client = _client(client_id)
    await provider.register_client(client)
    redirect_url = await provider.authorize(
        client,
        AuthorizationParams(
            state=state,
            scopes=["foodlog.read"],
            code_challenge=_pkce_challenge("verifier"),
            redirect_uri=AnyUrl("https://claude.ai/api/mcp/auth_callback"),
            redirect_uri_provided_explicitly=True,
            resource="https://foodlog.example.com/mcp",
        ),
    )
    return redirect_url.rsplit("=", 1)[1]


def _configure_oauth_test_settings(monkeypatch, db_session) -> None:
    monkeypatch.setattr(
        "foodlog.config.settings.foodlog_public_base_url",
        "https://foodlog.example.com",
    )
    monkeypatch.setattr("foodlog.config.settings.foodlog_oauth_login_secret", "secret")
    monkeypatch.setattr("foodlog.api.dependencies._session_factory", lambda: db_session)


def _expire_pending_authorization(db_session, request_id: str) -> None:
    pending = db_session.get(OAuthPendingAuthorization, request_id)
    assert pending is not None
    pending.expires_at = utcnow() - datetime.timedelta(seconds=1)
    db_session.commit()


def test_healthz_is_public(client):
    resp = client.get("/healthz", headers={})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_rest_routes_require_oauth(raw_client):
    resp = raw_client.get("/entries")

    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer")


def test_health_requires_oauth(raw_client):
    resp = raw_client.get("/health")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_oauth_consent_flow_issues_code(client, db_session, monkeypatch):
    _configure_oauth_test_settings(monkeypatch, db_session)

    provider = FoodLogOAuthProvider(lambda: db_session)
    request_id = await _create_pending_authorization(
        provider, "client_test", "state-abc"
    )

    resp = client.get(f"/oauth/consent?request_id={request_id}")

    assert resp.status_code == 200
    assert "Authorize FoodLog" in resp.text
    assert "foodlog.read" in resp.text
    assert request_id in resp.text

    resp = client.post(
        "/oauth/consent",
        data={"request_id": request_id, "login_secret": "wrong"},
    )

    assert resp.status_code == 401

    request_id = await _create_pending_authorization(
        provider, "client_second", "state-123"
    )

    resp = client.post(
        "/oauth/consent",
        data={"request_id": request_id, "login_secret": "secret"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    callback = urlsplit(resp.headers["location"])
    callback_query = parse_qs(callback.query)
    assert f"{callback.scheme}://{callback.netloc}{callback.path}" == (
        "https://claude.ai/api/mcp/auth_callback"
    )
    assert callback_query["code"]
    assert callback_query["state"] == ["state-123"]


def test_oauth_consent_missing_request_returns_404(client, db_session, monkeypatch):
    _configure_oauth_test_settings(monkeypatch, db_session)

    resp = client.get("/oauth/consent?request_id=missing")

    assert resp.status_code == 404


def test_oauth_consent_post_missing_request_id_returns_404(
    client, db_session, monkeypatch
):
    _configure_oauth_test_settings(monkeypatch, db_session)

    resp = client.post(
        "/oauth/consent",
        data={"login_secret": "secret"},
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_oauth_consent_expired_request_returns_404(
    client, db_session, monkeypatch
):
    _configure_oauth_test_settings(monkeypatch, db_session)
    provider = FoodLogOAuthProvider(lambda: db_session)
    request_id = await _create_pending_authorization(
        provider, "client_expired", "state-expired"
    )
    _expire_pending_authorization(db_session, request_id)

    resp = client.get(f"/oauth/consent?request_id={request_id}")

    assert resp.status_code == 404

    resp = client.post(
        "/oauth/consent",
        data={"request_id": request_id, "login_secret": "secret"},
    )

    assert resp.status_code == 404
