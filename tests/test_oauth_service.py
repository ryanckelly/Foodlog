import datetime

from foodlog.db.models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthPendingAuthorization,
    OAuthRefreshToken,
)


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
