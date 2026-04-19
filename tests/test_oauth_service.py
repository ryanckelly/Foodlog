import base64
import datetime
import hashlib
import json

import pytest
from foodlog.db.models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthPendingAuthorization,
    OAuthRefreshToken,
)
from foodlog.services.oauth import (
    FOODLOG_SCOPES,
    FoodLogOAuthProvider,
    FoodLogTokenVerifier,
    hash_token,
    login_secret_matches,
)
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyUrl


def test_oauth_models_persist(db_session):
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    client = OAuthClient(
        client_id="client_123",
        redirect_uris_json='["https://claude.ai/api/mcp/auth_callback"]',
        grant_types_json='["authorization_code","refresh_token"]',
        response_types_json='["code"]',
        scope="foodlog.read foodlog.write",
        client_name="Claude",
        token_endpoint_auth_method="none",
        client_id_issued_at=1_700_000_000,
    )
    pending = OAuthPendingAuthorization(
        request_id="req_123",
        client_id="client_123",
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        redirect_uri_provided_explicitly=True,
        scopes_json='["foodlog.read"]',
        state="state",
        code_challenge="challenge",
        resource="https://foodlog.example.com/mcp",
        expires_at=now + datetime.timedelta(minutes=5),
    )
    code = OAuthAuthorizationCode(
        code_hash="code_hash",
        client_id="client_123",
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        redirect_uri_provided_explicitly=True,
        scopes_json='["foodlog.read"]',
        code_challenge="challenge",
        resource="https://foodlog.example.com/mcp",
        expires_at=now + datetime.timedelta(minutes=5),
    )
    access = OAuthAccessToken(
        token_hash="access_hash",
        client_id="client_123",
        scopes_json='["foodlog.read"]',
        resource="https://foodlog.example.com/mcp",
        expires_at=1_700_003_600,
    )
    refresh = OAuthRefreshToken(
        token_hash="refresh_hash",
        client_id="client_123",
        scopes_json='["foodlog.read"]',
        expires_at=1_707_776_000,
    )

    db_session.add_all([client, pending, code, access, refresh])
    db_session.commit()

    assert db_session.get(OAuthClient, "client_123").client_name == "Claude"

    fetched_pending = db_session.get(OAuthPendingAuthorization, "req_123")
    fetched_code = db_session.get(OAuthAuthorizationCode, "code_hash")

    assert fetched_pending.client_id == "client_123"
    assert fetched_pending.expires_at.tzinfo is None
    assert fetched_pending.expires_at > now
    assert fetched_code.resource == "https://foodlog.example.com/mcp"
    assert fetched_code.expires_at.tzinfo is None
    assert fetched_code.expires_at > now
    assert db_session.get(OAuthAccessToken, "access_hash").client_id == "client_123"
    assert db_session.get(OAuthRefreshToken, "refresh_hash").client_id == "client_123"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="client_test",
        redirect_uris=[AnyUrl("https://claude.ai/api/mcp/auth_callback")],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=" ".join(FOODLOG_SCOPES),
        client_name="Claude",
        client_id_issued_at=1_700_000_000,
    )


def _client_with_redirect(client_id: str, redirect_uri: str) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl(redirect_uri)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=" ".join(FOODLOG_SCOPES),
        client_name="Claude",
        client_id_issued_at=1_700_000_000,
    )


@pytest.mark.asyncio
async def test_register_and_load_client(db_session, monkeypatch):
    monkeypatch.setattr("foodlog.config.settings.foodlog_public_base_url", "https://foodlog.example.com")
    provider = FoodLogOAuthProvider(lambda: db_session)
    await provider.register_client(_client())

    loaded = await provider.get_client("client_test")
    assert loaded is not None
    assert loaded.client_id == "client_test"
    assert loaded.client_name == "Claude"
    assert str(loaded.redirect_uris[0]) == "https://claude.ai/api/mcp/auth_callback"


@pytest.mark.asyncio
async def test_loaded_client_allows_loopback_callback_port_changes(db_session):
    provider = FoodLogOAuthProvider(lambda: db_session)
    await provider.register_client(
        _client_with_redirect("loopback_client", "http://localhost:1234/callback")
    )

    loaded = await provider.get_client("loopback_client")

    assert loaded is not None
    redirect_uri = AnyUrl("http://localhost:5678/callback")
    assert loaded.validate_redirect_uri(redirect_uri) == redirect_uri


@pytest.mark.asyncio
async def test_loaded_client_keeps_exact_redirect_matching_for_non_loopback(db_session):
    provider = FoodLogOAuthProvider(lambda: db_session)
    await provider.register_client(
        _client_with_redirect("https_client", "https://foodlog.example.com/callback")
    )

    loaded = await provider.get_client("https_client")

    assert loaded is not None
    exact_uri = AnyUrl("https://foodlog.example.com/callback")
    assert loaded.validate_redirect_uri(exact_uri) == exact_uri
    with pytest.raises(InvalidRedirectUriError):
        loaded.validate_redirect_uri(AnyUrl("https://foodlog.example.com/other"))


@pytest.mark.asyncio
async def test_authorize_creates_pending_consent_request(db_session, monkeypatch):
    monkeypatch.setattr("foodlog.config.settings.foodlog_public_base_url", "https://foodlog.example.com")
    provider = FoodLogOAuthProvider(lambda: db_session)
    client = _client()
    await provider.register_client(client)

    redirect_url = await provider.authorize(
        client,
        AuthorizationParams(
            state="abc",
            scopes=["foodlog.read"],
            code_challenge=_pkce_challenge("verifier"),
            redirect_uri=AnyUrl("https://claude.ai/api/mcp/auth_callback"),
            redirect_uri_provided_explicitly=True,
            resource="https://foodlog.example.com/mcp",
        ),
    )

    assert redirect_url.startswith("https://foodlog.example.com/oauth/consent?request_id=")
    request_id = redirect_url.rsplit("=", 1)[1]
    pending = provider.get_pending_authorization(request_id)
    assert pending is not None
    assert pending.client_id == "client_test"
    assert json.loads(pending.scopes_json) == ["foodlog.read"]


@pytest.mark.asyncio
async def test_issue_code_and_exchange_tokens(db_session, monkeypatch):
    monkeypatch.setattr("foodlog.config.settings.foodlog_public_base_url", "https://foodlog.example.com")
    provider = FoodLogOAuthProvider(lambda: db_session)
    client = _client()
    await provider.register_client(client)
    redirect_url = await provider.authorize(
        client,
        AuthorizationParams(
            state="abc",
            scopes=["foodlog.read", "foodlog.write"],
            code_challenge=_pkce_challenge("verifier"),
            redirect_uri=AnyUrl("https://claude.ai/api/mcp/auth_callback"),
            redirect_uri_provided_explicitly=True,
            resource="https://foodlog.example.com/mcp",
        ),
    )
    request_id = redirect_url.rsplit("=", 1)[1]

    callback_url = provider.approve_pending_authorization(request_id)
    assert callback_url.startswith("https://claude.ai/api/mcp/auth_callback?code=")
    code = callback_url.split("code=", 1)[1].split("&", 1)[0]

    auth_code = await provider.load_authorization_code(client, code)
    assert auth_code is not None
    tokens = await provider.exchange_authorization_code(client, auth_code)
    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.expires_in == 3600
    assert tokens.scope == "foodlog.read foodlog.write"

    verifier = FoodLogTokenVerifier(lambda: db_session)
    access = await verifier.verify_token(tokens.access_token)
    assert access is not None
    assert access.client_id == "client_test"
    assert access.resource == "https://foodlog.example.com/mcp"


@pytest.mark.asyncio
async def test_refresh_token_rotates(db_session, monkeypatch):
    monkeypatch.setattr("foodlog.config.settings.foodlog_public_base_url", "https://foodlog.example.com")
    provider = FoodLogOAuthProvider(lambda: db_session)
    client = _client()
    await provider.register_client(client)
    redirect_url = await provider.authorize(
        client,
        AuthorizationParams(
            state=None,
            scopes=["foodlog.read"],
            code_challenge=_pkce_challenge("verifier"),
            redirect_uri=AnyUrl("https://claude.ai/api/mcp/auth_callback"),
            redirect_uri_provided_explicitly=True,
            resource="https://foodlog.example.com/mcp",
        ),
    )
    code = provider.approve_pending_authorization(redirect_url.rsplit("=", 1)[1]).split("code=", 1)[1].split("&", 1)[0]
    tokens = await provider.exchange_authorization_code(client, await provider.load_authorization_code(client, code))
    loaded_refresh = await provider.load_refresh_token(client, tokens.refresh_token)

    rotated = await provider.exchange_refresh_token(client, loaded_refresh, ["foodlog.read"])
    assert rotated.refresh_token != tokens.refresh_token
    assert await provider.load_refresh_token(client, tokens.refresh_token) is None
    assert await provider.load_refresh_token(client, rotated.refresh_token) is not None


@pytest.mark.asyncio
async def test_revoke_refresh_token_revokes_paired_access_token(db_session, monkeypatch):
    monkeypatch.setattr("foodlog.config.settings.foodlog_public_base_url", "https://foodlog.example.com")
    provider = FoodLogOAuthProvider(lambda: db_session)
    client = _client()
    await provider.register_client(client)
    redirect_url = await provider.authorize(
        client,
        AuthorizationParams(
            state=None,
            scopes=["foodlog.read"],
            code_challenge=_pkce_challenge("verifier"),
            redirect_uri=AnyUrl("https://claude.ai/api/mcp/auth_callback"),
            redirect_uri_provided_explicitly=True,
            resource="https://foodlog.example.com/mcp",
        ),
    )
    code = provider.approve_pending_authorization(redirect_url.rsplit("=", 1)[1]).split("code=", 1)[1].split("&", 1)[0]
    auth_code = await provider.load_authorization_code(client, code)
    tokens = await provider.exchange_authorization_code(client, auth_code)
    loaded_refresh = await provider.load_refresh_token(client, tokens.refresh_token)
    verifier = FoodLogTokenVerifier(lambda: db_session)

    assert await verifier.verify_token(tokens.access_token) is not None

    await provider.revoke_token(loaded_refresh)

    assert await provider.load_refresh_token(client, tokens.refresh_token) is None
    assert await verifier.verify_token(tokens.access_token) is None


def test_hash_token_is_deterministic_and_not_plaintext():
    value = "secret-token"
    assert hash_token(value) == hash_token(value)
    assert hash_token(value) != value
    assert len(hash_token(value)) == 64


def test_login_secret_matches_fails_when_unset(monkeypatch):
    monkeypatch.setattr("foodlog.config.settings.foodlog_oauth_login_secret", "")

    assert login_secret_matches("") is False
    assert login_secret_matches("candidate") is False


def test_login_secret_matches_non_empty_secret(monkeypatch):
    monkeypatch.setattr("foodlog.config.settings.foodlog_oauth_login_secret", "secret")

    assert login_secret_matches("secret") is True
    assert login_secret_matches("wrong") is False
