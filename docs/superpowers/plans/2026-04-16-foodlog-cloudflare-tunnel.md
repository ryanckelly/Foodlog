# FoodLog Public Access via Cloudflare Tunnel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add public HTTPS access to foodlog via Cloudflare Tunnel with bearer token auth, enabling Claude Android via claude.ai custom connectors.

**Architecture:** Keep the existing Tailscale sidecar for local/tailnet access. Add a `cloudflared` container (same network namespace) that creates an outbound tunnel to Cloudflare, routing `foodlog.ryanckelly.ca` → `http://localhost:3474`. Add FastAPI bearer-token middleware that protects every endpoint (no path exemptions, no localhost exemption) — single shared secret, fail-closed if unset.

**Tech Stack:** Python 3.12, FastAPI, Starlette middleware, Docker Compose, `cloudflare/cloudflared`, Cloudflare Zero Trust Tunnels, MCP Python SDK

---

## File Map

| File | Responsibility |
|------|---------------|
| `foodlog/config.py` | Add `foodlog_auth_token: str = ""` setting |
| `foodlog/api/auth.py` | NEW — `BearerTokenMiddleware` (fail-closed bearer auth) |
| `foodlog/api/app.py` | Register the middleware on the app |
| `mcp_server/server.py` | Add `foodlog.ryanckelly.ca` to transport security allowlist |
| `tests/test_auth.py` | NEW — middleware unit tests (401/200/503 paths) |
| `tests/conftest.py` | Test fixture sets `FOODLOG_AUTH_TOKEN` and supplies header on all requests |
| `tests/test_api.py` | (No code change needed — fixture supplies header) |
| `docker-compose.yml` | Add `cloudflared` service with `TUNNEL_TOKEN` env |
| `.env.example` | Add `FOODLOG_AUTH_TOKEN`, `CLOUDFLARE_TUNNEL_TOKEN` placeholders |
| `.env` | Real token values (gitignored) |
| `.mcp.json` | DELETED — project-scoped config can't safely carry a secret |
| `doc/README.md` | Update integration section with the new auth + connector steps |

---

### Task 1: Add Auth Token Setting to Config

**Files:**
- Modify: `/opt/foodlog/foodlog/config.py`
- Modify: `/opt/foodlog/.env.example`

Adds the single environment variable the middleware reads.

- [ ] **Step 1: Add field to Settings**

Edit `/opt/foodlog/foodlog/config.py`. Find:
```python
    foodlog_db_path: str = "/data/foodlog.db"
    foodlog_host: str = "127.0.0.1"
    foodlog_port: int = 8042
```

Add a line directly below:
```python
    foodlog_auth_token: str = ""
```

(Keep default as empty string; middleware will refuse to start if unset.)

- [ ] **Step 2: Verify config still loads**

```bash
cd /opt/foodlog && source .venv/bin/activate && python -c "from foodlog.config import settings; print('token set:', bool(settings.foodlog_auth_token))"
```
Expected: `token set: False` (or True if an existing `.env` already has the key — also fine).

- [ ] **Step 3: Update .env.example**

Edit `/opt/foodlog/.env.example`. Append these two lines at the bottom:
```
# Public access (Cloudflare Tunnel)
FOODLOG_AUTH_TOKEN=generate_with_openssl_rand_hex_32
CLOUDFLARE_TUNNEL_TOKEN=paste_tunnel_token_from_cloudflare_dashboard
```

- [ ] **Step 4: Commit**

```bash
cd /opt/foodlog
git add foodlog/config.py .env.example
git commit -m "feat: add FOODLOG_AUTH_TOKEN setting"
```

---

### Task 2: Bearer Token Middleware (TDD)

**Files:**
- Create: `/opt/foodlog/foodlog/api/auth.py`
- Create: `/opt/foodlog/tests/test_auth.py`

- [ ] **Step 1: Write the failing tests**

Create `/opt/foodlog/tests/test_auth.py`:
```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from foodlog.api.auth import BearerTokenMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BearerTokenMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


@pytest.fixture
def set_token(monkeypatch):
    def _set(value: str | None):
        if value is None:
            monkeypatch.setattr(
                "foodlog.config.settings.foodlog_auth_token", ""
            )
        else:
            monkeypatch.setattr(
                "foodlog.config.settings.foodlog_auth_token", value
            )

    return _set


def test_missing_token_header_returns_401(set_token):
    set_token("secret-token")
    client = TestClient(_make_app())
    resp = client.get("/ping")
    assert resp.status_code == 401


def test_wrong_token_returns_401(set_token):
    set_token("secret-token")
    client = TestClient(_make_app())
    resp = client.get("/ping", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_valid_token_returns_200(set_token):
    set_token("secret-token")
    client = TestClient(_make_app())
    resp = client.get("/ping", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_unset_token_returns_503(set_token):
    set_token("")
    client = TestClient(_make_app())
    resp = client.get(
        "/ping", headers={"Authorization": "Bearer anything"}
    )
    assert resp.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest tests/test_auth.py -v 2>&1 | tail -5
```
Expected: FAIL with `ModuleNotFoundError: No module named 'foodlog.api.auth'`.

- [ ] **Step 3: Implement the middleware**

Create `/opt/foodlog/foodlog/api/auth.py`:
```python
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from foodlog.config import settings


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require Authorization: Bearer <token> on every request.

    Behavior:
    - If FOODLOG_AUTH_TOKEN is unset, returns 503 on every request
      (fail-closed — refuse to serve without a configured secret).
    - If Authorization header is missing or doesn't match, returns 401.
    - Otherwise delegates to the wrapped app.
    """

    async def dispatch(self, request: Request, call_next):
        expected_token = settings.foodlog_auth_token
        if not expected_token:
            return JSONResponse(
                {"detail": "FOODLOG_AUTH_TOKEN not configured"},
                status_code=503,
            )

        header = request.headers.get("Authorization", "")
        if header != f"Bearer {expected_token}":
            return JSONResponse(
                {"detail": "Invalid or missing bearer token"},
                status_code=401,
            )

        return await call_next(request)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest tests/test_auth.py -v 2>&1 | tail -10
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /opt/foodlog
git add foodlog/api/auth.py tests/test_auth.py
git commit -m "feat: bearer token auth middleware (fail-closed)"
```

---

### Task 3: Wire Middleware into FastAPI App

**Files:**
- Modify: `/opt/foodlog/foodlog/api/app.py`
- Modify: `/opt/foodlog/tests/conftest.py`
- Modify: `/opt/foodlog/tests/test_api.py` (one test helper — `_seed_entries`)

All existing tests will start returning 401. Fix by setting a known token in the test env and making the `client` fixture attach the header.

- [ ] **Step 1: Add middleware to app.py**

Edit `/opt/foodlog/foodlog/api/app.py`. Find the `create_app()` function. Right after `app = FastAPI(title="FoodLog", version="0.1.0", lifespan=lifespan)`, add:
```python
    from foodlog.api.auth import BearerTokenMiddleware
    app.add_middleware(BearerTokenMiddleware)
```

- [ ] **Step 2: Update conftest.py to set token and attach header**

Read `/opt/foodlog/tests/conftest.py` first. Replace its contents with:
```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from foodlog.api.app import create_app
from foodlog.api.dependencies import get_db
from foodlog.db.models import Base

TEST_TOKEN = "test-token-for-pytest"


@pytest.fixture(autouse=True)
def _set_test_token(monkeypatch):
    """Every test runs with a known bearer token so middleware lets requests through."""
    monkeypatch.setattr(
        "foodlog.config.settings.foodlog_auth_token", TEST_TOKEN
    )


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # TestClient defaults: attach bearer header to every request
    test_client = TestClient(
        app, headers={"Authorization": f"Bearer {TEST_TOKEN}"}
    )
    # Use context manager so lifespan runs (required for mounted MCP app)
    with test_client as ctx:
        yield ctx
```

Key changes:
1. `_set_test_token` autouse fixture ensures every test has the token configured.
2. `client` fixture passes `headers={"Authorization": ...}` to `TestClient` so every request carries the header.

- [ ] **Step 3: Run the full test suite**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest -v 2>&1 | tail -15
```
Expected: 46 passed (42 pre-existing + 4 auth tests). Every existing test should still pass since TestClient auto-attaches the header.

- [ ] **Step 4: Verify unauthed requests really get blocked**

Add this single test at the end of `/opt/foodlog/tests/test_api.py`:
```python
def test_requests_without_header_get_401(db_session):
    """Sanity check: middleware rejects requests that skip the fixture-added header."""
    from fastapi.testclient import TestClient

    from foodlog.api.app import create_app
    from foodlog.api.dependencies import get_db

    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    raw_client = TestClient(app)  # No Authorization header
    with raw_client as ctx:
        resp = ctx.get("/health")
    assert resp.status_code == 401
```

- [ ] **Step 5: Run tests again**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest -v 2>&1 | tail -5
```
Expected: 47 passed.

- [ ] **Step 6: Commit**

```bash
cd /opt/foodlog
git add foodlog/api/app.py tests/conftest.py tests/test_api.py
git commit -m "feat: protect all endpoints with bearer token middleware"
```

---

### Task 4: Add Public Hostname to MCP Transport Security

**Files:**
- Modify: `/opt/foodlog/mcp_server/server.py`

The MCP SDK's DNS rebinding protection currently only allows localhost and Tailscale. Add the Cloudflare hostname.

- [ ] **Step 1: Update allowed hosts and origins**

Edit `/opt/foodlog/mcp_server/server.py`. Find `_default_transport_security()`. In `allowed_hosts`, add these two entries after the Tailscale entries and before `"testserver"`:
```python
            "foodlog.ryanckelly.ca",
            "foodlog.ryanckelly.ca:*",
```

In `allowed_origins`, add these two entries after the Tailscale entry:
```python
            "https://foodlog.ryanckelly.ca",
            "https://foodlog.ryanckelly.ca:*",
```

The resulting function should look exactly like:
```python
def _default_transport_security() -> TransportSecuritySettings:
    """Allow localhost and Tailscale MagicDNS hostnames."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "foodlog",
            "foodlog:*",
            "foodlog.tailf67313.ts.net",
            "foodlog.tailf67313.ts.net:*",
            "foodlog.ryanckelly.ca",
            "foodlog.ryanckelly.ca:*",
            "testserver",  # for pytest TestClient
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            "https://foodlog.tailf67313.ts.net:*",
            "https://foodlog.ryanckelly.ca",
            "https://foodlog.ryanckelly.ca:*",
        ],
    )
```

- [ ] **Step 2: Run tests**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest -q 2>&1 | tail -3
```
Expected: 47 passed.

- [ ] **Step 3: Commit**

```bash
cd /opt/foodlog
git add mcp_server/server.py
git commit -m "feat: allow foodlog.ryanckelly.ca in MCP transport security"
```

---

### Task 5: Remove Project-Scoped .mcp.json

**Files:**
- Delete: `/opt/foodlog/.mcp.json`

The project-scoped config can't safely carry a literal bearer token (committed to git). The user-scoped registration in `~/.claude.json` already holds the working URL and is where the token will live.

- [ ] **Step 1: Delete the file**

```bash
rm /opt/foodlog/.mcp.json
```

- [ ] **Step 2: Commit**

```bash
cd /opt/foodlog
git add -A
git commit -m "chore: remove project-scoped .mcp.json; user-scoped registration is authoritative"
```

---

### Task 6: Add cloudflared Service to docker-compose.yml

**Files:**
- Modify: `/opt/foodlog/docker-compose.yml`

- [ ] **Step 1: Append the cloudflared service**

Read the current `/opt/foodlog/docker-compose.yml`. After the `tailscale:` service block (the last existing service), add this new service block indented at the same level as `foodlog:` and `tailscale:`:

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: foodlog-cloudflared
    network_mode: service:tailscale  # Share network namespace with tailscale/foodlog
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    command: tunnel --no-autoupdate run
    restart: unless-stopped
    depends_on:
      foodlog:
        condition: service_started
```

- [ ] **Step 2: Validate compose syntax**

```bash
cd /opt/foodlog && docker compose config 2>&1 | grep -E "(cloudflared|TUNNEL_TOKEN|error)" | head -5
```
Expected: `cloudflared` service appears; `TUNNEL_TOKEN` line present; no errors.

(The token itself is empty in `.env` at this stage — that's fine for config validation. The real token comes in Task 7.)

- [ ] **Step 3: Commit**

```bash
cd /opt/foodlog
git add docker-compose.yml
git commit -m "feat: add cloudflared sidecar for public HTTPS access"
```

---

### Task 7: Generate Secrets and Set Up Cloudflare Tunnel (USER MANUAL)

**Files:**
- Modify: `/opt/foodlog/.env` (gitignored)
- External: Cloudflare Zero Trust dashboard

- [ ] **Step 1: Generate the auth token**

```bash
openssl rand -hex 32
```
Copy the output (64 hex chars).

- [ ] **Step 2: Set up the Cloudflare Tunnel**

1. Open https://one.dash.cloudflare.com/ → **Networks → Tunnels → Create a tunnel**
2. Connector type: **Cloudflared**
3. Tunnel name: `foodlog`
4. After creation, the dashboard shows install commands — ignore the install part; just **copy the token** (long string starting with `eyJ...`).
5. Click through to the **Public Hostname** tab:
   - Subdomain: `foodlog`
   - Domain: `ryanckelly.ca`
   - Type: `HTTP`
   - URL: `localhost:3474`
6. Save.

DNS is auto-configured — Cloudflare creates a CNAME `foodlog.ryanckelly.ca` pointing to the tunnel. No manual DNS edits.

- [ ] **Step 3: Add both tokens to .env**

Edit `/opt/foodlog/.env` and add these two lines (replace placeholders with the actual tokens):
```
FOODLOG_AUTH_TOKEN=<openssl rand -hex 32 output from Step 1>
CLOUDFLARE_TUNNEL_TOKEN=<tunnel token from Step 2>
```

Set tight permissions:
```bash
chmod 600 /opt/foodlog/.env
```

- [ ] **Step 4: Sanity check the file has both**

```bash
grep -E "^(FOODLOG_AUTH_TOKEN|CLOUDFLARE_TUNNEL_TOKEN)=." /opt/foodlog/.env | wc -l
```
Expected: `2` (both variables populated).

---

### Task 8: Deploy — Rebuild & Restart Stack

**Files:**
- None (deploy-only).

- [ ] **Step 1: Rebuild foodlog image and restart all services**

```bash
cd /opt/foodlog
docker compose up -d --build 2>&1 | tail -10
```
Expected: `foodlog`, `foodlog-tailscale`, `foodlog-cloudflared` all `Started` or `Recreated`. Tailscale should be healthy.

- [ ] **Step 2: Verify all three containers running**

```bash
docker compose ps
```
Expected: Three services, all `running`. `foodlog-tailscale` is `healthy`.

- [ ] **Step 3: Check cloudflared connected**

```bash
docker logs foodlog-cloudflared 2>&1 | tail -15
```
Look for: `Registered tunnel connection` messages (usually 4 of them — `connIndex=0..3` to different Cloudflare edge locations).

If you see `failed to connect`, the token is wrong. Re-check Step 3 of Task 7.

- [ ] **Step 4: Verify foodlog app started**

```bash
docker logs foodlog 2>&1 | tail -10
```
Expected: uvicorn startup, no stack traces, no `FOODLOG_AUTH_TOKEN not configured` errors.

---

### Task 9: Smoke Tests

**Files:**
- None (verification only).

- [ ] **Step 1: Unauthenticated localhost → 401**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3473/health
```
Expected: `401`.

- [ ] **Step 2: Authenticated localhost → 200**

```bash
TOKEN=$(grep '^FOODLOG_AUTH_TOKEN=' /opt/foodlog/.env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:3473/health
echo
```
Expected: `{"status":"ok","fatsecret":true,"usda":true}`.

- [ ] **Step 3: Today's entries still accessible**

```bash
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:3473/summary/daily?date=$(date +%F)" | python3 -m json.tool
```
Expected: The breakfast + lunch entries logged previously. If today's date has no entries yet, an empty summary is returned and that's fine.

- [ ] **Step 4: Unauthenticated public URL → 401**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://foodlog.ryanckelly.ca/health
```
Expected: `401`. If you get a connection error or 502, the tunnel isn't connected; see Task 8 Step 3.

- [ ] **Step 5: Authenticated public URL → 200**

```bash
curl -s -H "Authorization: Bearer $TOKEN" https://foodlog.ryanckelly.ca/health
echo
```
Expected: `{"status":"ok","fatsecret":true,"usda":true}`.

- [ ] **Step 6: MCP endpoint through public URL**

```bash
curl -sL -X POST https://foodlog.ryanckelly.ca/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' \
  | head -3
```
Expected: SSE response with `"protocolVersion":"2024-11-05"` and `"serverInfo"`. If you get 401, the bearer token didn't propagate — check that `$TOKEN` is populated.

---

### Task 10: Re-Register Claude Code MCP with Header

**Files:**
- External: `~/.claude.json` (user-scoped MCP config)

- [ ] **Step 1: Remove old user-scoped registration**

```bash
claude mcp remove foodlog --scope user 2>&1 | tail -2
```

- [ ] **Step 2: Re-add with the Authorization header**

```bash
TOKEN=$(grep '^FOODLOG_AUTH_TOKEN=' /opt/foodlog/.env | cut -d= -f2)
claude mcp add --transport http --scope user foodlog http://localhost:3473/mcp \
  --header "Authorization: Bearer $TOKEN"
```
Expected: `Added HTTP MCP server foodlog ...`.

- [ ] **Step 3: Verify Claude Code sees it**

```bash
claude mcp list 2>&1 | grep foodlog
```
Expected: `foodlog: http://localhost:3473/mcp - ✓ Connected`.

If you see `Failed to connect`: docker compose isn't running, or the token in `.claude.json` doesn't match the one in `.env`. Fix one or the other.

---

### Task 11: Add claude.ai Custom Connector (USER MANUAL)

**Files:**
- External: claude.ai Settings → Connectors

- [ ] **Step 1: Open the connector UI**

Go to https://claude.ai → **Settings → Connectors → Add custom connector**.

- [ ] **Step 2: Configure**

- Name: `FoodLog`
- Remote MCP server URL: `https://foodlog.ryanckelly.ca/mcp`
- Under authentication / custom headers:
  - Header name: `Authorization`
  - Header value: `Bearer <paste the FOODLOG_AUTH_TOKEN value here>`

- [ ] **Step 3: Save and test**

Save the connector. Start a new claude.ai conversation (web or Android). Ask: **"What did I eat today?"** — Claude should invoke `get_daily_summary` and report the day's totals.

If tools don't appear:
- Make sure the connector is enabled in the conversation (toggle in the connector picker).
- Check the URL ends with `/mcp` (not `/`).
- Verify the bearer value doesn't have extra whitespace or `Bearer Bearer ...` duplication.

---

### Task 12: Update Deployment README

**Files:**
- Modify: `/opt/foodlog/doc/README.md`

- [ ] **Step 1: Update the Environment Variables table**

Edit `/opt/foodlog/doc/README.md`. In the Environment Variables table, add these two rows after `TS_HOSTNAME`:
```
| FOODLOG_AUTH_TOKEN | Bearer token required on every request (generate via `openssl rand -hex 32`) | Yes |
| CLOUDFLARE_TUNNEL_TOKEN | Token from Cloudflare Zero Trust tunnel setup | Yes |
```

- [ ] **Step 2: Update the Integration section**

Find the `### Claude Code (local)` subsection. Replace its contents with:
```markdown
### Claude Code (local)

User-scoped registration:
\`\`\`bash
TOKEN=$(grep '^FOODLOG_AUTH_TOKEN=' /opt/foodlog/.env | cut -d= -f2)
claude mcp add --transport http --scope user foodlog http://localhost:3473/mcp \
  --header "Authorization: Bearer $TOKEN"
\`\`\`

There is no project-scoped `.mcp.json` — the bearer token makes per-project committed config unsafe.
```

Find the `### Claude Android (remote)` subsection. Replace its contents with:
```markdown
### Claude Android (remote)

Add a custom connector at https://claude.ai → Settings → Connectors → Add custom connector:

- Name: `FoodLog`
- URL: `https://foodlog.ryanckelly.ca/mcp`
- Custom header — `Authorization: Bearer <FOODLOG_AUTH_TOKEN value>`

Once saved on claude.ai (web), the connector is available in Claude Android automatically. No Tailscale required — requests traverse Cloudflare's tunnel, not your tailnet.
```

- [ ] **Step 3: Add a Cloudflare Tunnel section to Prerequisites**

In the Prerequisites list, add a third bullet:
```markdown
- A Cloudflare account with a zone for `ryanckelly.ca` (domain DNS on Cloudflare)
```

- [ ] **Step 4: Commit**

```bash
cd /opt/foodlog
git add doc/README.md
git commit -m "docs: update README for bearer auth + Cloudflare connector"
```

---

## Self-Review

**1. Spec coverage:**
- Architecture (three containers, shared network namespace): Task 6 ✓
- Bearer token middleware (fail-closed): Tasks 1, 2, 3 ✓
- MCP transport security allowlist: Task 4 ✓
- Cloudflare Tunnel setup: Task 7 ✓
- Test updates (fixture header + unauth regression test): Task 3 ✓
- Deployment smoke tests: Task 9 ✓
- Claude Code re-registration: Task 10 ✓
- Claude.ai custom connector: Task 11 ✓
- README updates: Task 12 ✓
- `.mcp.json` removal: Task 5 ✓

**2. Placeholder scan:** No TBDs. All code blocks are complete. All commands are concrete.

**3. Type consistency:** `foodlog_auth_token` (attribute name) consistent across config.py and middleware. `FOODLOG_AUTH_TOKEN` (env var) consistent across `.env.example`, README, shell commands, compose file. `BearerTokenMiddleware` name consistent across auth.py, app.py, and tests.

---

## Rollback

If anything in Tasks 6–11 breaks and you need to get back to the Tailscale-only working state:

```bash
cd /opt/foodlog
git reset --hard <SHA of last commit on master before this plan>
docker compose down
# Remove the cloudflared container and volumes
docker compose up -d
# Revert Claude Code registration to no-header version
claude mcp remove foodlog --scope user
claude mcp add --transport http --scope user foodlog http://localhost:3473/mcp
```

SQLite data at `/opt/foodlog/data/foodlog.db` survives any of this.
