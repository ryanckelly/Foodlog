import base64
import datetime
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from foodlog.config import settings
from foodlog.db.models import OAuthAccessToken, OAuthPendingAuthorization
from foodlog.services.oauth import (
    FOODLOG_SCOPES,
    FoodLogOAuthProvider,
    hash_token,
    utcnow,
)
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


def _add_access_token(db_session, token: str, scopes: list[str]) -> None:
    db_session.add(
        OAuthAccessToken(
            token_hash=hash_token(token),
            client_id=f"client-{token}",
            scopes_json=json.dumps(scopes),
            resource=settings.public_mcp_resource_url,
            expires_at=int(datetime.datetime.now(datetime.UTC).timestamp()) + 3600,
        )
    )
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


def test_rest_routes_reject_wrong_token(raw_client):
    resp = raw_client.get(
        "/entries", headers={"Authorization": "Bearer definitely-wrong"}
    )

    assert resp.status_code == 401


def test_rest_write_routes_require_write_scope(raw_client, db_session):
    token = "read-only-token"
    _add_access_token(db_session, token, ["foodlog.read"])

    resp = raw_client.post(
        "/entries",
        headers={"Authorization": f"Bearer {token}"},
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken",
                "quantity": 1.0,
                "unit": "serving",
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "raw_input": "chicken",
            }
        ],
    )

    assert resp.status_code == 403


def test_protected_resource_metadata(raw_client):
    resp = raw_client.get("/.well-known/oauth-protected-resource/mcp")

    assert resp.status_code == 200
    data = resp.json()
    assert data["resource"] == "https://foodlog.example.com/mcp"
    assert data["authorization_servers"] == ["https://foodlog.example.com/"]
    assert "foodlog.read" in data["scopes_supported"]


def test_authorization_server_metadata(raw_client):
    resp = raw_client.get("/.well-known/oauth-authorization-server")

    assert resp.status_code == 200
    data = resp.json()
    assert data["issuer"] == "https://foodlog.example.com/"
    assert data["authorization_endpoint"] == "https://foodlog.example.com/authorize"
    assert data["token_endpoint"] == "https://foodlog.example.com/token"
    assert data["registration_endpoint"] == "https://foodlog.example.com/register"


def test_dynamic_registration_and_authorize_redirect(raw_client):
    register_resp = raw_client.post(
        "/register",
        json={
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "foodlog.read foodlog.write",
            "client_name": "Claude",
        },
    )
    assert register_resp.status_code == 201
    client_id = register_resp.json()["client_id"]

    authorize_resp = raw_client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "scope": "foodlog.read foodlog.write",
            "state": "state-123",
            "code_challenge": _pkce_challenge("verifier"),
            "code_challenge_method": "S256",
            "resource": "https://foodlog.example.com/mcp",
        },
        follow_redirects=False,
    )

    assert authorize_resp.status_code == 302
    location = authorize_resp.headers["location"]
    assert location.startswith("https://foodlog.example.com/oauth/consent")
    assert "request_id=" in location


def test_dynamic_registration_accepts_default_confidential_client(raw_client):
    register_resp = raw_client.post(
        "/register",
        json={
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "foodlog.read foodlog.write",
            "client_name": "Claude",
        },
    )

    assert register_resp.status_code == 201
    data = register_resp.json()
    assert data["token_endpoint_auth_method"] == "client_secret_post"
    assert data["client_secret"]
    assert data["client_id"]


def test_mcp_without_token_returns_oauth_challenge(raw_client):
    resp = raw_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )

    assert resp.status_code == 401
    assert "resource_metadata" in resp.headers["www-authenticate"]


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
