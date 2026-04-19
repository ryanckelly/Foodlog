# FoodLog Cloudflare OAuth Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Tailscale deployment with a single-container Cloudflare Tunnel deployment and first-party OAuth for Claude remote MCP connectors.

**Architecture:** The FoodLog FastAPI app becomes the OAuth resource server for `/mcp` and the single-user OAuth authorization server for Claude connector setup. OAuth clients, pending approvals, authorization codes, access tokens, and refresh tokens are persisted in the existing SQLite database under `/data`. The Docker image runs both `uvicorn` and `cloudflared`; Compose owns one `foodlog` service with no Tailscale dependency.

**Tech Stack:** Python 3.12, FastAPI, Starlette, SQLAlchemy, SQLite, MCP Python SDK auth primitives, Docker Compose, Cloudflare Tunnel.

---

## File Map

| File | Responsibility |
|------|----------------|
| `foodlog/config.py` | Add Cloudflare/OAuth deployment settings and token lifetime constants |
| `foodlog/db/models.py` | Add OAuth persistence tables |
| `foodlog/db/database.py` | Enable SQLite busy timeout and WAL pragmas for safer concurrent reads |
| `foodlog/services/oauth.py` | New OAuth provider, token verifier, hashing, redirect validation, token rotation |
| `foodlog/api/auth.py` | New middleware protecting REST routes with OAuth access tokens |
| `foodlog/api/oauth.py` | New consent-page and deployment health routes |
| `foodlog/api/dependencies.py` | Add test/reset helper for cached session factory |
| `foodlog/api/app.py` | Compose REST, OAuth, and MCP routes at the public origin |
| `mcp_server/server.py` | Accept OAuth provider/verifier/settings and expose `/mcp` without Tailscale hosts |
| `tests/conftest.py` | Seed a valid OAuth access token for existing API tests |
| `tests/test_oauth_service.py` | New unit tests for OAuth persistence and validation |
| `tests/test_oauth_api.py` | New integration tests for discovery, consent, token exchange, and REST auth |
| `tests/test_api.py` | Update `/health` expectations and MCP auth expectations |
| `tests/test_mcp.py` | Assert the MCP server is configured with OAuth when requested |
| `Dockerfile` | Install `cloudflared`, copy entrypoint, expose internal app port |
| `docker-entrypoint.sh` | Start `cloudflared` and FoodLog app, forward signals |
| `docker-compose.yml` | Replace Tailscale sidecar with a single `foodlog` service |
| `.env.example` | Replace Tailscale env vars with Cloudflare/OAuth env vars |
| `.gitignore` | Remove `tailscale-state/`; keep `data/` and secrets ignored |
| `serve.json` | Delete obsolete Tailscale serve config |
| `DEPLOY_WHEN_BACK.md` | Replace stale Tailscale instructions with Cloudflare/OAuth manual steps |
| `doc/README.md` | Update operations docs for the new deployment |

---

## Task 1: Add Deployment Settings and SQLite Pragmas

**Files:**
- Modify: `/opt/foodlog/foodlog/config.py`
- Modify: `/opt/foodlog/foodlog/db/database.py`
- Test: `/opt/foodlog/tests/test_db.py`

- [ ] **Step 1: Add failing config tests**

Append these tests to `/opt/foodlog/tests/test_db.py`:

```python
from foodlog.config import Settings


def test_cloudflare_oauth_settings_defaults():
    settings = Settings()
    assert settings.cloudflare_tunnel_token == ""
    assert settings.foodlog_public_base_url == ""
    assert settings.foodlog_oauth_login_secret == ""
    assert settings.oauth_authorization_code_ttl_seconds == 300
    assert settings.oauth_access_token_ttl_seconds == 3600
    assert settings.oauth_refresh_token_ttl_seconds == 90 * 24 * 60 * 60


def test_public_mcp_resource_url_strips_trailing_slash():
    settings = Settings(foodlog_public_base_url="https://foodlog.example.com/")
    assert settings.public_base_url == "https://foodlog.example.com"
    assert settings.public_mcp_resource_url == "https://foodlog.example.com/mcp"
```

- [ ] **Step 2: Run the config tests and verify failure**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_db.py::test_cloudflare_oauth_settings_defaults tests/test_db.py::test_public_mcp_resource_url_strips_trailing_slash -v
```

Expected: fails with `AttributeError` for the new settings.

- [ ] **Step 3: Add settings**

Edit `/opt/foodlog/foodlog/config.py` so the `Settings` class is:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    fatsecret_consumer_key: str = ""
    fatsecret_consumer_secret: str = ""
    usda_api_key: str = ""
    foodlog_db_path: str = "/data/foodlog.db"
    foodlog_host: str = "127.0.0.1"
    foodlog_port: int = 8042
    cloudflare_tunnel_token: str = ""
    foodlog_public_base_url: str = ""
    foodlog_oauth_login_secret: str = ""
    oauth_authorization_code_ttl_seconds: int = 5 * 60
    oauth_access_token_ttl_seconds: int = 60 * 60
    oauth_refresh_token_ttl_seconds: int = 90 * 24 * 60 * 60

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.foodlog_db_path}"

    @property
    def public_base_url(self) -> str:
        return self.foodlog_public_base_url.rstrip("/")

    @property
    def public_mcp_resource_url(self) -> str:
        return f"{self.public_base_url}/mcp"

    @property
    def fatsecret_configured(self) -> bool:
        return bool(self.fatsecret_consumer_key and self.fatsecret_consumer_secret)

    @property
    def usda_configured(self) -> bool:
        return bool(self.usda_api_key)


settings = Settings()
```

- [ ] **Step 4: Add SQLite connection pragmas**

Replace `/opt/foodlog/foodlog/db/database.py` with:

```python
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from foodlog.config import settings


def _configure_sqlite(engine: Engine) -> None:
    """Enable safer SQLite behavior for app + local dashboard readers."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_engine(db_url: str | None = None):
    url = db_url or settings.database_url
    db_path = url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, echo=False)
    if url.startswith("sqlite:///"):
        _configure_sqlite(engine)
    return engine


def get_session_factory(engine=None):
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine)
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_db.py -v
```

Expected: all `tests/test_db.py` tests pass.

- [ ] **Step 6: Commit**

```bash
cd /opt/foodlog
git add foodlog/config.py foodlog/db/database.py tests/test_db.py
git commit -m "feat: add Cloudflare OAuth deployment settings"
```

---

## Task 2: Add OAuth Persistence Models

**Files:**
- Modify: `/opt/foodlog/foodlog/db/models.py`
- Test: `/opt/foodlog/tests/test_oauth_service.py`

- [ ] **Step 1: Write failing model tests**

Create `/opt/foodlog/tests/test_oauth_service.py` with:

```python
import datetime

from foodlog.db.models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthPendingAuthorization,
    OAuthRefreshToken,
)


def test_oauth_models_persist(db_session):
    now = datetime.datetime.now(datetime.UTC)
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
    assert db_session.get(OAuthPendingAuthorization, "req_123").client_id == "client_123"
    assert db_session.get(OAuthAuthorizationCode, "code_hash").resource == "https://foodlog.example.com/mcp"
    assert db_session.get(OAuthAccessToken, "access_hash").client_id == "client_123"
    assert db_session.get(OAuthRefreshToken, "refresh_hash").client_id == "client_123"
```

- [ ] **Step 2: Run the model test and verify failure**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_service.py::test_oauth_models_persist -v
```

Expected: import failure for the new OAuth model classes.

- [ ] **Step 3: Add OAuth models**

Update `/opt/foodlog/foodlog/db/models.py` imports:

```python
import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
```

Append these classes after `FoodEntry`:

```python
class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_uris_json: Mapped[str] = mapped_column(Text)
    grant_types_json: Mapped[str] = mapped_column(Text)
    response_types_json: Mapped[str] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    contacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tos_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    jwks_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    jwks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    software_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_endpoint_auth_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_id_issued_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_secret_expires_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OAuthPendingAuthorization(Base):
    __tablename__ = "oauth_pending_authorizations"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean)
    scopes_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_challenge: Mapped[str] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class OAuthAuthorizationCode(Base):
    __tablename__ = "oauth_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean)
    scopes_json: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class OAuthAccessToken(Base):
    __tablename__ = "oauth_access_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    scopes_json: Mapped[str] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[int] = mapped_column(Integer)
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class OAuthRefreshToken(Base):
    __tablename__ = "oauth_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    scopes_json: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[int] = mapped_column(Integer)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Run the model test**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_service.py::test_oauth_models_persist -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
cd /opt/foodlog
git add foodlog/db/models.py tests/test_oauth_service.py
git commit -m "feat: add OAuth persistence models"
```

---

## Task 3: Implement OAuth Provider and Token Verifier

**Files:**
- Create: `/opt/foodlog/foodlog/services/oauth.py`
- Modify: `/opt/foodlog/tests/test_oauth_service.py`

- [ ] **Step 1: Add failing service tests**

Append these tests to `/opt/foodlog/tests/test_oauth_service.py`:

```python
import base64
import hashlib
import json
import time

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from foodlog.services.oauth import (
    FOODLOG_SCOPES,
    FoodLogOAuthProvider,
    FoodLogTokenVerifier,
    hash_token,
)


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


def test_hash_token_is_deterministic_and_not_plaintext():
    value = "secret-token"
    assert hash_token(value) == hash_token(value)
    assert hash_token(value) != value
    assert len(hash_token(value)) == 64
```

- [ ] **Step 2: Run service tests and verify failure**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_service.py -v
```

Expected: import failure for `foodlog.services.oauth`.

- [ ] **Step 3: Create OAuth service**

Create `/opt/foodlog/foodlog/services/oauth.py`:

```python
import datetime
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    OAuthToken,
    RefreshToken,
    RegistrationError,
    TokenError,
    TokenVerifier,
)
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl, AnyUrl
from sqlalchemy.orm import Session

from foodlog.config import settings
from foodlog.db.models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthPendingAuthorization,
    OAuthRefreshToken,
)

FOODLOG_SCOPES = ("foodlog.read", "foodlog.write")
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def now_epoch() -> int:
    return int(time.time())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json_list(values: list[str] | tuple[str, ...] | None) -> str:
    return json.dumps(list(values or []), separators=(",", ":"))


def _load_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    loaded = json.loads(value)
    return [str(item) for item in loaded]


def _new_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def _append_query(url: str, values: dict[str, str | None]) -> str:
    clean = {key: val for key, val in values.items() if val is not None}
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(clean)}"


def _redirect_uri_allowed(uri: str) -> bool:
    if uri == CLAUDE_CALLBACK:
        return True
    if uri.startswith("http://localhost:") and uri.endswith("/callback"):
        return True
    if uri.startswith("http://127.0.0.1:") and uri.endswith("/callback"):
        return True
    return uri.startswith("https://")


class FoodLogOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self.session_factory() as session:
            row = session.get(OAuthClient, client_id)
            if row is None:
                return None
            return self._client_from_row(row)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        redirect_uris = [str(uri) for uri in client_info.redirect_uris or []]
        if not redirect_uris or any(not _redirect_uri_allowed(uri) for uri in redirect_uris):
            raise RegistrationError("invalid_redirect_uri", "Unsupported redirect URI")
        method = client_info.token_endpoint_auth_method or "none"
        if method != "none":
            raise RegistrationError("invalid_client_metadata", "Only public PKCE clients are supported")
        client_id = client_info.client_id or _new_secret("client")
        issued_at = client_info.client_id_issued_at or now_epoch()
        with self.session_factory() as session:
            session.merge(
                OAuthClient(
                    client_id=client_id,
                    client_secret=None,
                    redirect_uris_json=_json_list(redirect_uris),
                    grant_types_json=_json_list(client_info.grant_types),
                    response_types_json=_json_list(client_info.response_types),
                    scope=client_info.scope or " ".join(FOODLOG_SCOPES),
                    client_name=client_info.client_name,
                    client_uri=str(client_info.client_uri) if client_info.client_uri else None,
                    logo_uri=str(client_info.logo_uri) if client_info.logo_uri else None,
                    contacts_json=_json_list(client_info.contacts),
                    tos_uri=str(client_info.tos_uri) if client_info.tos_uri else None,
                    policy_uri=str(client_info.policy_uri) if client_info.policy_uri else None,
                    jwks_uri=str(client_info.jwks_uri) if client_info.jwks_uri else None,
                    jwks_json=json.dumps(client_info.jwks) if client_info.jwks else None,
                    software_id=client_info.software_id,
                    software_version=client_info.software_version,
                    token_endpoint_auth_method=method,
                    client_id_issued_at=issued_at,
                    client_secret_expires_at=None,
                )
            )
            session.commit()
            client_info.client_id = client_id
            client_info.client_id_issued_at = issued_at

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        scopes = params.scopes or list(FOODLOG_SCOPES)
        invalid = [scope for scope in scopes if scope not in FOODLOG_SCOPES]
        if invalid:
            raise AuthorizeError("invalid_scope", f"Unsupported scopes: {' '.join(invalid)}")
        resource = params.resource or settings.public_mcp_resource_url
        if resource != settings.public_mcp_resource_url:
            raise AuthorizeError("invalid_request", "Invalid resource")
        request_id = _new_secret("authreq")
        expires_at = utcnow() + datetime.timedelta(minutes=10)
        with self.session_factory() as session:
            session.add(
                OAuthPendingAuthorization(
                    request_id=request_id,
                    client_id=client.client_id or "",
                    redirect_uri=str(params.redirect_uri),
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    scopes_json=_json_list(scopes),
                    state=params.state,
                    code_challenge=params.code_challenge,
                    resource=resource,
                    expires_at=expires_at,
                )
            )
            session.commit()
        return f"{settings.public_base_url}/oauth/consent?request_id={request_id}"

    def get_pending_authorization(self, request_id: str) -> OAuthPendingAuthorization | None:
        with self.session_factory() as session:
            row = session.get(OAuthPendingAuthorization, request_id)
            if row is None:
                return None
            session.expunge(row)
            return row

    def approve_pending_authorization(self, request_id: str) -> str:
        with self.session_factory() as session:
            pending = session.get(OAuthPendingAuthorization, request_id)
            if pending is None or pending.expires_at < utcnow():
                raise ValueError("Authorization request expired")
            code = _new_secret("code")
            session.add(
                OAuthAuthorizationCode(
                    code_hash=hash_token(code),
                    client_id=pending.client_id,
                    redirect_uri=pending.redirect_uri,
                    redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
                    scopes_json=pending.scopes_json,
                    code_challenge=pending.code_challenge,
                    resource=pending.resource,
                    expires_at=utcnow()
                    + datetime.timedelta(seconds=settings.oauth_authorization_code_ttl_seconds),
                )
            )
            session.delete(pending)
            session.commit()
            return _append_query(pending.redirect_uri, {"code": code, "state": pending.state})

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with self.session_factory() as session:
            row = session.get(OAuthAuthorizationCode, hash_token(authorization_code))
            if row is None or row.consumed_at is not None or row.client_id != client.client_id:
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=_load_json_list(row.scopes_json),
                expires_at=row.expires_at.replace(tzinfo=datetime.UTC).timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=AnyUrl(row.redirect_uri),
                redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                resource=row.resource,
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with self.session_factory() as session:
            row = session.get(OAuthAuthorizationCode, hash_token(authorization_code.code))
            if row is None or row.consumed_at is not None:
                raise TokenError("invalid_grant", "authorization code has already been used")
            row.consumed_at = utcnow()
            access_token, refresh_token = self._create_tokens(
                session=session,
                client_id=authorization_code.client_id,
                scopes=authorization_code.scopes,
                resource=authorization_code.resource,
            )
            session.commit()
            return OAuthToken(
                access_token=access_token,
                expires_in=settings.oauth_access_token_ttl_seconds,
                scope=" ".join(authorization_code.scopes),
                refresh_token=refresh_token,
            )

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        with self.session_factory() as session:
            row = session.get(OAuthRefreshToken, hash_token(refresh_token))
            if row is None or row.revoked_at is not None or row.client_id != client.client_id:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=_load_json_list(row.scopes_json),
                expires_at=row.expires_at,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        with self.session_factory() as session:
            row = session.get(OAuthRefreshToken, hash_token(refresh_token.token))
            if row is None or row.revoked_at is not None:
                raise TokenError("invalid_grant", "refresh token is no longer valid")
            row.revoked_at = utcnow()
            access_token, new_refresh_token = self._create_tokens(
                session=session,
                client_id=client.client_id or "",
                scopes=scopes,
                resource=settings.public_mcp_resource_url,
            )
            row.replaced_by_hash = hash_token(new_refresh_token)
            session.commit()
            return OAuthToken(
                access_token=access_token,
                expires_in=settings.oauth_access_token_ttl_seconds,
                scope=" ".join(scopes),
                refresh_token=new_refresh_token,
            )

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await FoodLogTokenVerifier(self.session_factory).verify_token(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_hash = hash_token(token.token)
        with self.session_factory() as session:
            access = session.get(OAuthAccessToken, token_hash)
            refresh = session.get(OAuthRefreshToken, token_hash)
            now = utcnow()
            if access is not None:
                access.revoked_at = now
                if access.refresh_token_hash:
                    paired = session.get(OAuthRefreshToken, access.refresh_token_hash)
                    if paired is not None:
                        paired.revoked_at = now
            if refresh is not None:
                refresh.revoked_at = now
            session.commit()

    def _create_tokens(
        self, session: Session, client_id: str, scopes: list[str], resource: str | None
    ) -> tuple[str, str]:
        access_token = _new_secret("access")
        refresh_token = _new_secret("refresh")
        access_hash = hash_token(access_token)
        refresh_hash = hash_token(refresh_token)
        session.add(
            OAuthAccessToken(
                token_hash=access_hash,
                client_id=client_id,
                scopes_json=_json_list(scopes),
                resource=resource,
                expires_at=now_epoch() + settings.oauth_access_token_ttl_seconds,
                refresh_token_hash=refresh_hash,
            )
        )
        session.add(
            OAuthRefreshToken(
                token_hash=refresh_hash,
                client_id=client_id,
                scopes_json=_json_list(scopes),
                expires_at=now_epoch() + settings.oauth_refresh_token_ttl_seconds,
            )
        )
        return access_token, refresh_token

    def _client_from_row(self, row: OAuthClient) -> OAuthClientInformationFull:
        return OAuthClientInformationFull(
            client_id=row.client_id,
            client_secret=row.client_secret,
            redirect_uris=[AnyUrl(uri) for uri in _load_json_list(row.redirect_uris_json)],
            token_endpoint_auth_method=row.token_endpoint_auth_method,
            grant_types=_load_json_list(row.grant_types_json),
            response_types=_load_json_list(row.response_types_json),
            scope=row.scope,
            client_name=row.client_name,
            client_uri=AnyHttpUrl(row.client_uri) if row.client_uri else None,
            logo_uri=AnyHttpUrl(row.logo_uri) if row.logo_uri else None,
            contacts=_load_json_list(row.contacts_json),
            tos_uri=AnyHttpUrl(row.tos_uri) if row.tos_uri else None,
            policy_uri=AnyHttpUrl(row.policy_uri) if row.policy_uri else None,
            jwks_uri=AnyHttpUrl(row.jwks_uri) if row.jwks_uri else None,
            jwks=json.loads(row.jwks_json) if row.jwks_json else None,
            software_id=row.software_id,
            software_version=row.software_version,
            client_id_issued_at=row.client_id_issued_at,
            client_secret_expires_at=row.client_secret_expires_at,
        )


class FoodLogTokenVerifier(TokenVerifier):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        with self.session_factory() as session:
            row = session.get(OAuthAccessToken, hash_token(token))
            if row is None or row.revoked_at is not None:
                return None
            if row.expires_at <= now_epoch():
                return None
            if row.resource != settings.public_mcp_resource_url:
                return None
            return AccessToken(
                token=token,
                client_id=row.client_id,
                scopes=_load_json_list(row.scopes_json),
                expires_at=row.expires_at,
                resource=row.resource,
            )


def login_secret_matches(candidate: str) -> bool:
    return hmac.compare_digest(candidate, settings.foodlog_oauth_login_secret)
```

- [ ] **Step 4: Run service tests**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_service.py -v
```

Expected: all OAuth service tests pass.

- [ ] **Step 5: Commit**

```bash
cd /opt/foodlog
git add foodlog/services/oauth.py tests/test_oauth_service.py
git commit -m "feat: implement FoodLog OAuth provider"
```

---

## Task 4: Add OAuth Consent and Public Health Routes

**Files:**
- Create: `/opt/foodlog/foodlog/api/oauth.py`
- Test: `/opt/foodlog/tests/test_oauth_api.py`

- [ ] **Step 1: Write failing API tests**

Create `/opt/foodlog/tests/test_oauth_api.py`:

```python
import base64
import hashlib
from urllib.parse import parse_qs, urlparse


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def test_healthz_is_public(client):
    resp = client.get("/healthz", headers={})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_oauth_consent_flow_issues_code(client, monkeypatch):
    monkeypatch.setattr("foodlog.config.settings.foodlog_public_base_url", "https://foodlog.example.com")
    monkeypatch.setattr("foodlog.config.settings.foodlog_oauth_login_secret", "secret")

    register_resp = client.post(
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
    assert register_resp.status_code in (200, 201)
    client_id = register_resp.json()["client_id"]

    authorize_resp = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "scope": "foodlog.read foodlog.write",
            "state": "state-123",
            "code_challenge": _challenge("verifier"),
            "code_challenge_method": "S256",
            "resource": "https://foodlog.example.com/mcp",
        },
        follow_redirects=False,
    )
    assert authorize_resp.status_code == 302
    consent_location = authorize_resp.headers["location"]
    assert consent_location.startswith("https://foodlog.example.com/oauth/consent?request_id=")

    request_id = parse_qs(urlparse(consent_location).query)["request_id"][0]
    page_resp = client.get(f"/oauth/consent?request_id={request_id}")
    assert page_resp.status_code == 200
    assert "Authorize FoodLog" in page_resp.text

    bad_resp = client.post(
        "/oauth/consent",
        data={"request_id": request_id, "login_secret": "wrong"},
        follow_redirects=False,
    )
    assert bad_resp.status_code == 401

    good_resp = client.post(
        "/oauth/consent",
        data={"request_id": request_id, "login_secret": "secret"},
        follow_redirects=False,
    )
    assert good_resp.status_code == 302
    callback = good_resp.headers["location"]
    assert callback.startswith("https://claude.ai/api/mcp/auth_callback?code=")
    assert "state=state-123" in callback
```

- [ ] **Step 2: Run API tests and verify failure**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_api.py -v
```

Expected: fails because `create_app()` does not expose `/healthz`, `/register`, or consent routes.

- [ ] **Step 3: Create OAuth API routes**

Create `/opt/foodlog/foodlog/api/oauth.py`:

```python
from html import escape

from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from foodlog.api.dependencies import get_session_factory_cached
from foodlog.services.oauth import FoodLogOAuthProvider, login_secret_matches

router = APIRouter()


def get_oauth_provider() -> FoodLogOAuthProvider:
    return FoodLogOAuthProvider(get_session_factory_cached())


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/oauth/consent", response_class=HTMLResponse)
def consent_page(request_id: str):
    provider = get_oauth_provider()
    pending = provider.get_pending_authorization(request_id)
    if pending is None:
        return HTMLResponse("Authorization request not found or expired", status_code=404)
    scopes = ", ".join(escape(scope) for scope in pending.scopes_json.strip("[]").replace('"', "").split(",") if scope)
    body = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Authorize FoodLog</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
  </head>
  <body>
    <main>
      <h1>Authorize FoodLog</h1>
      <p>Claude is requesting access to FoodLog.</p>
      <p>Scopes: {scopes}</p>
      <form method="post" action="/oauth/consent">
        <input type="hidden" name="request_id" value="{escape(request_id)}">
        <label>
          FoodLog secret
          <input name="login_secret" type="password" autocomplete="current-password" required>
        </label>
        <button type="submit">Authorize</button>
      </form>
    </main>
  </body>
</html>
"""
    return HTMLResponse(body)


@router.post("/oauth/consent")
async def approve_consent(request: Request):
    form = await request.form()
    request_id = str(form.get("request_id", ""))
    login_secret = str(form.get("login_secret", ""))
    if not login_secret_matches(login_secret):
        return JSONResponse({"detail": "Invalid FoodLog secret"}, status_code=401)
    provider = get_oauth_provider()
    try:
        callback_url = provider.approve_pending_authorization(request_id)
    except ValueError:
        return JSONResponse({"detail": "Authorization request not found or expired"}, status_code=404)
    return RedirectResponse(callback_url, status_code=302)
```

- [ ] **Step 4: Wire routes into app**

In `/opt/foodlog/foodlog/api/app.py`, add this import near the router imports inside `create_app()`:

```python
    from foodlog.api.oauth import router as oauth_router
```

Then include it before the existing REST routers:

```python
    app.include_router(oauth_router)
```

- [ ] **Step 5: Run API tests**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_api.py -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
cd /opt/foodlog
git add foodlog/api/oauth.py foodlog/api/app.py tests/test_oauth_api.py
git commit -m "feat: add FoodLog OAuth consent routes"
```

---

## Task 5: Protect REST Routes with OAuth Access Tokens

**Files:**
- Create: `/opt/foodlog/foodlog/api/auth.py`
- Modify: `/opt/foodlog/foodlog/api/app.py`
- Modify: `/opt/foodlog/foodlog/api/dependencies.py`
- Modify: `/opt/foodlog/tests/conftest.py`
- Modify: `/opt/foodlog/tests/test_api.py`
- Test: `/opt/foodlog/tests/test_oauth_api.py`

- [ ] **Step 1: Add failing REST auth tests**

Append to `/opt/foodlog/tests/test_oauth_api.py`:

```python
def test_rest_routes_require_oauth(raw_client):
    resp = raw_client.get("/entries")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer")


def test_health_requires_oauth(raw_client):
    resp = raw_client.get("/health")
    assert resp.status_code == 401
```

- [ ] **Step 2: Update conftest with raw and authenticated clients**

Replace `/opt/foodlog/tests/conftest.py` with:

```python
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from foodlog.api.app import create_app
from foodlog.api.dependencies import get_db, reset_session_factory_for_tests
from foodlog.config import settings
from foodlog.db.models import Base, OAuthAccessToken
from foodlog.services.oauth import hash_token

TEST_ACCESS_TOKEN = "test-access-token"


@pytest.fixture(autouse=True)
def _oauth_settings(monkeypatch):
    monkeypatch.setattr(settings, "foodlog_public_base_url", "https://foodlog.example.com")
    monkeypatch.setattr(settings, "foodlog_oauth_login_secret", "test-login-secret")


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    reset_session_factory_for_tests(SessionLocal)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        reset_session_factory_for_tests(None)


@pytest.fixture
def oauth_token(db_session):
    db_session.add(
        OAuthAccessToken(
            token_hash=hash_token(TEST_ACCESS_TOKEN),
            client_id="pytest-client",
            scopes_json='["foodlog.read","foodlog.write"]',
            resource=settings.public_mcp_resource_url,
            expires_at=int(datetime.datetime.now(datetime.UTC).timestamp()) + 3600,
        )
    )
    db_session.commit()
    return TEST_ACCESS_TOKEN


@pytest.fixture
def raw_client(db_session):
    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(raw_client, oauth_token):
    raw_client.headers.update({"Authorization": f"Bearer {oauth_token}"})
    yield raw_client
```

- [ ] **Step 3: Run tests and verify fixture failure**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_api.py::test_rest_routes_require_oauth -v
```

Expected: import failure for `reset_session_factory_for_tests` or missing middleware behavior.

- [ ] **Step 4: Add session factory reset helper**

Append to `/opt/foodlog/foodlog/api/dependencies.py`:

```python
def reset_session_factory_for_tests(session_factory):
    """Test-only hook so auth middleware and MCP tools use the in-memory DB."""
    global _session_factory
    _session_factory = session_factory
```

- [ ] **Step 5: Create OAuth REST middleware**

Create `/opt/foodlog/foodlog/api/auth.py`:

```python
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from foodlog.api.dependencies import get_session_factory_cached
from foodlog.config import settings
from foodlog.services.oauth import FoodLogTokenVerifier

PUBLIC_PATHS = (
    "/healthz",
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
    "/authorize",
    "/token",
    "/register",
    "/revoke",
    "/oauth/consent",
)


class OAuthResourceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path
        if request.method == "OPTIONS" or path == "/mcp" or path.startswith(PUBLIC_PATHS):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._unauthorized()
        verifier = FoodLogTokenVerifier(get_session_factory_cached())
        token = await verifier.verify_token(auth_header.removeprefix("Bearer ").strip())
        if token is None:
            return self._unauthorized()

        required_scope = "foodlog.read"
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            required_scope = "foodlog.write"
        if path == "/health":
            required_scope = "foodlog.read"
        if required_scope not in token.scopes:
            return JSONResponse({"detail": "Insufficient scope"}, status_code=403)

        request.state.oauth_token = token
        return await call_next(request)

    def _unauthorized(self):
        metadata_url = f'{settings.public_base_url}/.well-known/oauth-protected-resource/mcp'
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={
                "WWW-Authenticate": f'Bearer realm="foodlog", resource_metadata="{metadata_url}"'
            },
        )
```

- [ ] **Step 6: Register middleware**

In `/opt/foodlog/foodlog/api/app.py`, add after `app = FastAPI(title="FoodLog", version="0.1.0", lifespan=lifespan)`:

```python
    from foodlog.api.auth import OAuthResourceMiddleware

    app.add_middleware(OAuthResourceMiddleware)
```

- [ ] **Step 7: Update health test expectations**

In `/opt/foodlog/tests/test_api.py`, leave `test_health(client)` as-is because the authenticated fixture now sends a token. Add this test after `test_health`:

```python
def test_healthz_public(raw_client):
    resp = raw_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 8: Run auth and API tests**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_api.py tests/test_api.py -v
```

Expected: all selected tests pass except the MCP initialize test may now fail until Task 6 protects `/mcp` with SDK OAuth.

- [ ] **Step 9: Commit**

```bash
cd /opt/foodlog
git add foodlog/api/auth.py foodlog/api/app.py foodlog/api/dependencies.py tests/conftest.py tests/test_api.py tests/test_oauth_api.py
git commit -m "feat: protect REST routes with OAuth tokens"
```

---

## Task 6: Enable MCP OAuth Protection and Root-Level Discovery

**Files:**
- Modify: `/opt/foodlog/mcp_server/server.py`
- Modify: `/opt/foodlog/foodlog/api/app.py`
- Modify: `/opt/foodlog/tests/test_api.py`
- Modify: `/opt/foodlog/tests/test_mcp.py`
- Test: `/opt/foodlog/tests/test_oauth_api.py`

- [ ] **Step 1: Add failing MCP discovery tests**

Append to `/opt/foodlog/tests/test_oauth_api.py`:

```python
def test_protected_resource_metadata(raw_client):
    resp = raw_client.get("/.well-known/oauth-protected-resource/mcp")
    assert resp.status_code == 200
    data = resp.json()
    assert data["resource"] == "https://foodlog.example.com/mcp"
    assert data["authorization_servers"] == ["https://foodlog.example.com"]
    assert "foodlog.read" in data["scopes_supported"]


def test_mcp_without_token_returns_oauth_challenge(raw_client):
    resp = raw_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 401
    assert "resource_metadata" in resp.headers["www-authenticate"]
```

- [ ] **Step 2: Update MCP initialize test to use authenticated client**

In `/opt/foodlog/tests/test_api.py`, the existing `test_mcp_endpoint_initialize(client)` should continue using `client`, not `raw_client`. No code change is needed if the fixture already attaches the bearer token.

- [ ] **Step 3: Run MCP auth tests and verify failure**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_api.py::test_protected_resource_metadata tests/test_oauth_api.py::test_mcp_without_token_returns_oauth_challenge tests/test_api.py::test_mcp_endpoint_initialize -v
```

Expected: discovery route missing or `/mcp` not protected by MCP SDK OAuth.

- [ ] **Step 4: Update MCP server factory**

Replace `/opt/foodlog/mcp_server/server.py` imports at the top with:

```python
import datetime

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
```

Change `_default_transport_security()` to:

```python
def _default_transport_security() -> TransportSecuritySettings:
    """Allow local, test, and public Cloudflare host headers."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "foodlog",
            "foodlog:*",
            "foodlog.ryanckelly.ca",
            "foodlog.ryanckelly.ca:*",
            "foodlog.example.com",
            "foodlog.example.com:*",
            "testserver",
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            "https://foodlog.ryanckelly.ca",
            "https://foodlog.ryanckelly.ca:*",
            "https://foodlog.example.com",
            "https://foodlog.example.com:*",
        ],
    )
```

Change `create_mcp_server()` signature and FastMCP construction:

```python
def create_mcp_server(auth_server_provider=None, token_verifier=None) -> FastMCP:
    """Create the MCP server with tools that call services directly."""
    auth_settings = None
    if auth_server_provider is not None or token_verifier is not None:
        from foodlog.config import settings

        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl(settings.public_base_url),
            resource_server_url=AnyHttpUrl(settings.public_mcp_resource_url),
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["foodlog.read", "foodlog.write"],
                default_scopes=["foodlog.read", "foodlog.write"],
            ),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=["foodlog.read"],
        )

    mcp = FastMCP(
        "FoodLog",
        instructions=(
            "Food logging assistant. Use search_food to find nutrition data, "
            "then log_food to record meals. Use get_daily_summary to show totals. "
            "Always search before logging to get accurate nutrition values."
        ),
        streamable_http_path="/mcp",
        auth_server_provider=auth_server_provider,
        token_verifier=token_verifier,
        auth=auth_settings,
        transport_security=_default_transport_security(),
    )
```

Keep the existing tool definitions unchanged.

- [ ] **Step 5: Compose FastMCP routes at the app root**

In `/opt/foodlog/foodlog/api/app.py`, update app creation after `Base.metadata.create_all(engine)` to construct OAuth provider and verifier:

```python
        from foodlog.services.oauth import FoodLogOAuthProvider, FoodLogTokenVerifier

        session_factory = get_session_factory_cached()
        mcp = create_mcp_server(
            auth_server_provider=FoodLogOAuthProvider(session_factory),
            token_verifier=FoodLogTokenVerifier(session_factory),
        )
```

Because `mcp` is currently created before `lifespan`, move MCP creation above the lifespan but create it with provider/verifier using `get_session_factory_cached()` after settings are loaded:

```python
def create_app() -> FastAPI:
    from foodlog.services.oauth import FoodLogOAuthProvider, FoodLogTokenVerifier

    session_factory = get_session_factory_cached()
    mcp = create_mcp_server(
        auth_server_provider=FoodLogOAuthProvider(session_factory),
        token_verifier=FoodLogTokenVerifier(session_factory),
    )
```

Then replace:

```python
    app.mount("/mcp", mcp.streamable_http_app())
```

with:

```python
    mcp_app = mcp.streamable_http_app()
    for middleware in reversed(mcp_app.user_middleware):
        app.add_middleware(middleware.cls, *middleware.args, **middleware.kwargs)
    app.router.routes.extend(mcp_app.routes)
```

The resulting `create_app()` keeps the existing combined lifespan, includes OAuth and REST routers, and exposes FastMCP routes directly at `/mcp`, `/.well-known/oauth-protected-resource/mcp`, `/.well-known/oauth-authorization-server`, `/authorize`, `/token`, `/register`, and `/revoke`.

- [ ] **Step 6: Update MCP unit test**

Append to `/opt/foodlog/tests/test_mcp.py`:

```python
from foodlog.services.oauth import FoodLogOAuthProvider, FoodLogTokenVerifier


def test_mcp_server_can_enable_oauth(db_session):
    mcp = create_mcp_server(
        auth_server_provider=FoodLogOAuthProvider(lambda: db_session),
        token_verifier=FoodLogTokenVerifier(lambda: db_session),
    )
    assert mcp.settings.auth is not None
    assert str(mcp.settings.auth.resource_server_url) == "https://foodlog.example.com/mcp"
```

- [ ] **Step 7: Run MCP auth tests**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_oauth_api.py::test_protected_resource_metadata tests/test_oauth_api.py::test_mcp_without_token_returns_oauth_challenge tests/test_api.py::test_mcp_endpoint_initialize tests/test_mcp.py -v
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
cd /opt/foodlog
git add mcp_server/server.py foodlog/api/app.py tests/test_api.py tests/test_mcp.py tests/test_oauth_api.py
git commit -m "feat: protect MCP endpoint with OAuth"
```

---

## Task 7: Enforce Tool Scopes on MCP Calls

**Files:**
- Modify: `/opt/foodlog/mcp_server/server.py`
- Test: `/opt/foodlog/tests/test_mcp.py`

- [ ] **Step 1: Add scope metadata test**

Append to `/opt/foodlog/tests/test_mcp.py`:

```python
def test_mcp_tool_scope_policy_is_declared():
    from mcp_server.server import TOOL_REQUIRED_SCOPES

    assert TOOL_REQUIRED_SCOPES["search_food"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["get_entries"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["get_daily_summary"] == ["foodlog.read"]
    assert TOOL_REQUIRED_SCOPES["log_food"] == ["foodlog.write"]
    assert TOOL_REQUIRED_SCOPES["edit_entry"] == ["foodlog.write"]
    assert TOOL_REQUIRED_SCOPES["delete_entry"] == ["foodlog.write"]
```

- [ ] **Step 2: Add helper tests**

Append to `/opt/foodlog/tests/test_mcp.py`:

```python
import pytest
from mcp.server.auth.provider import AccessToken


def test_require_scope_allows_matching_scope(monkeypatch):
    from mcp_server import server

    monkeypatch.setattr(
        server,
        "get_access_token",
        lambda: AccessToken(
            token="token",
            client_id="client",
            scopes=["foodlog.read"],
            expires_at=9999999999,
            resource="https://foodlog.example.com/mcp",
        ),
    )

    server._require_scope("foodlog.read")


def test_require_scope_rejects_missing_scope(monkeypatch):
    from mcp_server import server

    monkeypatch.setattr(
        server,
        "get_access_token",
        lambda: AccessToken(
            token="token",
            client_id="client",
            scopes=["foodlog.read"],
            expires_at=9999999999,
            resource="https://foodlog.example.com/mcp",
        ),
    )

    with pytest.raises(PermissionError, match="Missing required scope"):
        server._require_scope("foodlog.write")
```

- [ ] **Step 3: Run scope tests and verify failure**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_mcp.py::test_mcp_tool_scope_policy_is_declared tests/test_mcp.py::test_require_scope_allows_matching_scope tests/test_mcp.py::test_require_scope_rejects_missing_scope -v
```

Expected: import failure for `TOOL_REQUIRED_SCOPES` and `_require_scope`.

- [ ] **Step 4: Add scope policy and helper**

Add this import near the top of `/opt/foodlog/mcp_server/server.py`:

```python
from mcp.server.auth.middleware.auth_context import get_access_token
```

Add below imports:

```python
TOOL_REQUIRED_SCOPES = {
    "search_food": ["foodlog.read"],
    "get_entries": ["foodlog.read"],
    "get_daily_summary": ["foodlog.read"],
    "log_food": ["foodlog.write"],
    "edit_entry": ["foodlog.write"],
    "delete_entry": ["foodlog.write"],
}


def _require_scope(scope: str) -> None:
    access_token = get_access_token()
    if access_token is None:
        return
    if scope not in access_token.scopes:
        raise PermissionError(f"Missing required scope: {scope}")
```

- [ ] **Step 5: Call helper from each tool**

In `/opt/foodlog/mcp_server/server.py`, add these exact calls as the first executable line in each tool body, immediately after each tool docstring:

```python
        _require_scope("foodlog.read")
```

Add that line to `search_food`, `get_entries`, and `get_daily_summary`.

```python
        _require_scope("foodlog.write")
```

Add that line to `log_food`, `edit_entry`, and `delete_entry`. Keep each existing function body unchanged after the inserted `_require_scope(...)` call.

- [ ] **Step 6: Run MCP tests**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest tests/test_mcp.py -v
```

Expected: all MCP tests pass.

- [ ] **Step 7: Commit**

```bash
cd /opt/foodlog
git add mcp_server/server.py tests/test_mcp.py
git commit -m "feat: enforce MCP tool scopes"
```

---

## Task 8: Update Docker Image and Compose for Single-Container Cloudflare

**Files:**
- Modify: `/opt/foodlog/Dockerfile`
- Create: `/opt/foodlog/docker-entrypoint.sh`
- Modify: `/opt/foodlog/docker-compose.yml`
- Modify: `/opt/foodlog/.env.example`
- Modify: `/opt/foodlog/.gitignore`
- Delete: `/opt/foodlog/serve.json`

- [ ] **Step 1: Replace Dockerfile**

Replace `/opt/foodlog/Dockerfile` with:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
      -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY foodlog/ ./foodlog/
COPY mcp_server/ ./mcp_server/

RUN pip install --no-cache-dir -e .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 3474

ENTRYPOINT ["docker-entrypoint.sh"]
```

- [ ] **Step 2: Create entrypoint**

Create `/opt/foodlog/docker-entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

required_vars=(
  CLOUDFLARE_TUNNEL_TOKEN
  FOODLOG_PUBLIC_BASE_URL
  FOODLOG_OAUTH_LOGIN_SECRET
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing required environment variable: ${var_name}" >&2
    exit 1
  fi
done

cleanup() {
  if [[ -n "${APP_PID:-}" ]]; then
    kill "${APP_PID}" 2>/dev/null || true
  fi
  if [[ -n "${TUNNEL_PID:-}" ]]; then
    kill "${TUNNEL_PID}" 2>/dev/null || true
  fi
}

trap cleanup TERM INT

cloudflared tunnel --no-autoupdate run &
TUNNEL_PID=$!

python -m foodlog.api.app &
APP_PID=$!

wait -n "${TUNNEL_PID}" "${APP_PID}"
exit_code=$?
cleanup
exit "${exit_code}"
```

- [ ] **Step 3: Replace Compose file**

Replace `/opt/foodlog/docker-compose.yml` with:

```yaml
services:
  foodlog:
    build: .
    container_name: foodlog
    environment:
      - TZ=${TZ}
      - PUID=${PUID}
      - PGID=${PGID}
      - FATSECRET_CONSUMER_KEY=${FATSECRET_CONSUMER_KEY}
      - FATSECRET_CONSUMER_SECRET=${FATSECRET_CONSUMER_SECRET}
      - USDA_API_KEY=${USDA_API_KEY}
      - FOODLOG_DB_PATH=/data/foodlog.db
      - FOODLOG_HOST=0.0.0.0
      - FOODLOG_PORT=3474
      - FOODLOG_PUBLIC_BASE_URL=${FOODLOG_PUBLIC_BASE_URL}
      - FOODLOG_OAUTH_LOGIN_SECRET=${FOODLOG_OAUTH_LOGIN_SECRET}
      - CLOUDFLARE_TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    ports:
      - "127.0.0.1:3474:3474"
    volumes:
      - ./data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3474/healthz', timeout=3).read()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    restart: unless-stopped
```

- [ ] **Step 4: Update `.env.example`**

Replace `/opt/foodlog/.env.example` with:

```env
# Required (matches /opt/docs/STANDARDS.md)
TZ=America/Halifax
PUID=1000
PGID=1000

# Nutrition API credentials
FATSECRET_CONSUMER_KEY=your_fatsecret_client_id_here
FATSECRET_CONSUMER_SECRET=your_fatsecret_client_secret_here
USDA_API_KEY=your_usda_api_key_here

# Server config
FOODLOG_DB_PATH=/data/foodlog.db
FOODLOG_HOST=0.0.0.0
FOODLOG_PORT=3474
FOODLOG_PUBLIC_BASE_URL=https://foodlog.ryanckelly.ca

# OAuth connector auth
FOODLOG_OAUTH_LOGIN_SECRET=generate_with_openssl_rand_hex_32

# Cloudflare Tunnel
CLOUDFLARE_TUNNEL_TOKEN=paste_tunnel_token_from_cloudflare_dashboard
```

- [ ] **Step 5: Update gitignore and delete serve config**

Edit `/opt/foodlog/.gitignore` so the Docker volumes section is:

```gitignore
# Docker volumes
data/
```

Delete `/opt/foodlog/serve.json`.

- [ ] **Step 6: Validate Compose**

Run:

```bash
cd /opt/foodlog
docker compose config >/tmp/foodlog-compose.yml
rg -n "foodlog|TUNNEL_TOKEN|tailscale" /tmp/foodlog-compose.yml
```

Expected: output contains `foodlog` and `TUNNEL_TOKEN`; output does not contain `tailscale`.

- [ ] **Step 7: Commit**

```bash
cd /opt/foodlog
git add Dockerfile docker-entrypoint.sh docker-compose.yml .env.example .gitignore serve.json
git commit -m "feat: replace Tailscale sidecar with Cloudflare container"
```

---

## Task 9: Update Deployment Documentation

**Files:**
- Modify: `/opt/foodlog/doc/README.md`
- Modify: `/opt/foodlog/DEPLOY_WHEN_BACK.md`

- [ ] **Step 1: Replace `DEPLOY_WHEN_BACK.md`**

Replace `/opt/foodlog/DEPLOY_WHEN_BACK.md` with:

```markdown
# When You're Back - Cloudflare OAuth Deployment

The Tailscale deployment has been superseded. FoodLog now deploys as one
container that runs the FastAPI/MCP app plus `cloudflared`.

## 1. Create Cloudflare Tunnel

Cloudflare Zero Trust -> Networks -> Tunnels -> Create tunnel:

- Name: `foodlog`
- Connector type: `cloudflared`
- Public hostname: `foodlog.ryanckelly.ca`
- Service: `http://localhost:3474`

Copy the tunnel token. It starts with `eyJ...`.

## 2. Add Secrets to `.env`

```bash
cd /opt/foodlog
openssl rand -hex 32
nano /opt/foodlog/.env
chmod 600 /opt/foodlog/.env
```

Required values:

```env
FOODLOG_PUBLIC_BASE_URL=https://foodlog.ryanckelly.ca
FOODLOG_OAUTH_LOGIN_SECRET=<openssl rand -hex 32 output>
CLOUDFLARE_TUNNEL_TOKEN=<Cloudflare tunnel token>
```

## 3. Deploy

```bash
cd /opt/foodlog
docker compose up -d --build
docker compose ps
docker logs foodlog --tail 50
curl -s https://foodlog.ryanckelly.ca/healthz
```

Expected health response:

```json
{"status":"ok"}
```

Unauthenticated MCP should return OAuth challenge headers:

```bash
curl -i -s -X POST https://foodlog.ryanckelly.ca/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  | head -20
```

Expected: `401` and `WWW-Authenticate` with `resource_metadata`.

## 4. Add Connector in Claude Web

Open https://claude.ai -> Settings -> Connectors -> Add custom connector:

- Name: `FoodLog`
- URL: `https://foodlog.ryanckelly.ca/mcp`

Complete the OAuth flow. When FoodLog asks for the secret, paste
`FOODLOG_OAUTH_LOGIN_SECRET`.

After that, Claude Android can use the connector from your Claude account.

## Troubleshooting

- Tunnel not connected: `docker logs foodlog --tail 100` and check Cloudflare token.
- OAuth fails before consent: verify `FOODLOG_PUBLIC_BASE_URL` matches the public hostname.
- Consent rejects secret: verify `.env` has the exact `FOODLOG_OAUTH_LOGIN_SECRET`.
- Reconnect needed: use Claude web or Claude Desktop, then Android will use the refreshed connector.

## Rollback

```bash
cd /opt/foodlog
docker compose down
git checkout <previous-working-commit>
docker compose up -d --build
```

SQLite data remains in `/opt/foodlog/data/foodlog.db`.
```

- [ ] **Step 2: Update `doc/README.md`**

Edit `/opt/foodlog/doc/README.md` to remove Tailscale setup steps and add this deployment summary near the top:

```markdown
## Deployment Model

FoodLog runs as one Docker Compose service:

- FastAPI REST API and MCP endpoint on internal port `3474`
- First-party OAuth endpoints for Claude remote MCP connectors
- `cloudflared` outbound tunnel process
- SQLite database mounted at `/data/foodlog.db`

No Tailscale sidecar is required. No inbound router port forward is required.
Cloudflare routes `https://foodlog.ryanckelly.ca/*` to
`http://localhost:3474` inside the container.
```

Replace the environment variable table rows for `TS_AUTHKEY` and `TS_HOSTNAME` with:

```markdown
| FOODLOG_PUBLIC_BASE_URL | Public HTTPS origin, e.g. `https://foodlog.ryanckelly.ca` | Yes |
| FOODLOG_OAUTH_LOGIN_SECRET | Single-user secret for OAuth consent page | Yes |
| CLOUDFLARE_TUNNEL_TOKEN | Token from Cloudflare Tunnel setup | Yes |
```

Add this connector section:

```markdown
### Claude Web and Android

Add the connector on Claude web or Claude Desktop:

- Name: `FoodLog`
- URL: `https://foodlog.ryanckelly.ca/mcp`

Claude will run the OAuth flow. Use `FOODLOG_OAUTH_LOGIN_SECRET` on the FoodLog
consent page. After the connector is connected, Claude Android can use it from
the same Claude account.
```

- [ ] **Step 3: Commit docs**

```bash
cd /opt/foodlog
git add doc/README.md DEPLOY_WHEN_BACK.md
git commit -m "docs: update deployment docs for Cloudflare OAuth"
```

---

## Task 10: Full Verification

**Files:**
- None unless verification finds defects.

- [ ] **Step 1: Run full test suite**

Run:

```bash
cd /opt/foodlog
source .venv/bin/activate
pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Build the Docker image**

Run:

```bash
cd /opt/foodlog
docker compose build foodlog
```

Expected: image builds without errors and includes `cloudflared`.

- [ ] **Step 3: Validate Compose has no Tailscale**

Run:

```bash
cd /opt/foodlog
docker compose config >/tmp/foodlog-compose.yml
rg -n "tailscale|TS_AUTHKEY|serve.json" /tmp/foodlog-compose.yml || true
```

Expected: no matches.

- [ ] **Step 4: Verify working tree**

Run:

```bash
cd /opt/foodlog
git status --short
```

Expected: clean working tree.

- [ ] **Step 5: Record verification in final response**

The final implementation response must include:

```text
Tests: pytest -q
Build: docker compose build foodlog
Compose check: no Tailscale references in docker compose config
```

If a command fails because required local secrets are missing, report the exact command and the failure instead of claiming success.

---

## Self-Review

Spec coverage:

- Drops Tailscale deployment path: Task 8 and Task 9.
- Single runtime container with app plus `cloudflared`: Task 8.
- OAuth connector flow: Tasks 3, 4, 5, and 6.
- SQLite persistence for OAuth state: Task 2 and Task 3.
- Protected `/mcp` with public-root OAuth discovery: Task 6.
- Existing REST routes protected: Task 5.
- MCP tool-level read/write scopes enforced: Task 7.
- Dashboard access through HTTP API and no SQLite DB container: Task 9 documentation.
- Deployment smoke expectations: Task 10 and `DEPLOY_WHEN_BACK.md`.

Placeholder scan:

- No `TBD`, `TODO`, `implement later`, or undefined placeholder steps.
- Every created file has concrete content.
- Every test task has an exact command and expected result.

Type consistency:

- `FOODLOG_PUBLIC_BASE_URL`, `FOODLOG_OAUTH_LOGIN_SECRET`, and `CLOUDFLARE_TUNNEL_TOKEN` match between config, Compose, env example, docs, and entrypoint.
- `FoodLogOAuthProvider`, `FoodLogTokenVerifier`, and `hash_token` are defined before later tasks import them.
- OAuth table names and model class names match between tests, models, and service code.
