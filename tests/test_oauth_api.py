import base64
import hashlib

import pytest
from foodlog.services.oauth import FOODLOG_SCOPES, FoodLogOAuthProvider
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


def test_healthz_is_public(client):
    resp = client.get("/healthz", headers={})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_oauth_consent_flow_issues_code(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "foodlog.config.settings.foodlog_public_base_url",
        "https://foodlog.example.com",
    )
    monkeypatch.setattr("foodlog.config.settings.foodlog_oauth_login_secret", "secret")
    monkeypatch.setattr("foodlog.api.dependencies._session_factory", lambda: db_session)

    provider = FoodLogOAuthProvider(lambda: db_session)
    request_id = await _create_pending_authorization(
        provider, "client_test", "state-abc"
    )

    resp = client.get(f"/oauth/consent?request_id={request_id}")

    assert resp.status_code == 200
    assert "Authorize FoodLog" in resp.text

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
    assert resp.headers["location"].startswith(
        "https://claude.ai/api/mcp/auth_callback?code="
    )
    assert "state=state-123" in resp.headers["location"]
