# FoodLog Public Access via Cloudflare Tunnel — Design Spec

## Overview

Add public HTTPS access to foodlog so it works with Claude Android (which connects via Anthropic's backend, not the phone's local network). Use a Cloudflare Tunnel to expose the existing FastAPI service at `foodlog.ryanckelly.ca` without opening any ports on the UDM Pro or exposing the home IP. Add bearer token authentication to every request — Tailscale-only access was insufficient because Anthropic's servers can't reach into the tailnet.

## Goals

- Claude Android can use the foodlog MCP tools via claude.ai custom connectors.
- No new ports opened on the UDM Pro (outbound-only CF tunnel).
- Home IP not exposed publicly (traffic egresses through Cloudflare).
- Single auth layer (bearer token) protects every endpoint, regardless of whether the client reaches the service via localhost, Tailscale, or Cloudflare.

## Non-Goals

- OAuth, SSO, or Cloudflare Access. Overkill for a single-user personal tool.
- Splitting REST and MCP onto different hosts. One service, one endpoint.
- Removing the Tailscale sidecar. It stays for local/tailnet access from other devices.

## Architecture

```
Claude Android ───HTTPS────→ Cloudflare Edge ────outbound tunnel──────┐
                                                                        ↓
claude.ai connector ──HTTPS──→ Cloudflare Edge ───outbound tunnel────┤
                                                                        ↓
Another tailnet device ─HTTPS→ foodlog.tailf67313.ts.net:3473 ────────┤
                                                                        ↓
Localhost ─────HTTP──────────→ localhost:3473 ───────────────────────┤
                                                                        ↓
                                          ┌────────────────────────────┴─────┐
                                          │   foodlog container              │
                                          │   uvicorn on 0.0.0.0:3474         │
                                          │   + bearer token middleware       │
                                          │   REST + MCP (/mcp)               │
                                          └──────────────────────────────────┘
```

Three containers share Tailscale's network namespace (same pattern as `/opt/ollama/`):

- `foodlog` — FastAPI + mounted MCP, listens on internal port 3474
- `foodlog-tailscale` — Tailscale sidecar, serves 3473→3474 for local + tailnet
- `foodlog-cloudflared` **(NEW)** — Cloudflare Tunnel connector, routes `foodlog.ryanckelly.ca` → `http://localhost:3474`

## Auth Model

**Single bearer token on every request.**

- FastAPI middleware checks `Authorization: Bearer <token>` on all endpoints.
- No path exemptions — auth applies to localhost as well as remote.
- Missing or wrong token → 401.
- Token generated once via `openssl rand -hex 32`, stored in `/opt/foodlog/.env` as `FOODLOG_AUTH_TOKEN`.

**Client configuration:**

| Client | How the token is supplied |
|--------|---------------------------|
| Claude Android | Set once in claude.ai connector config (custom header). Syncs to phone. |
| Claude Code (local) | Set once in `.mcp.json` as a request header. Attached automatically. |
| curl / debugging | Manual `-H "Authorization: Bearer <token>"` on each call. |

Rationale: bearer tokens are what MCP clients natively handle via custom-header config, and claude.ai's custom connector UI supports this. OAuth/Cloudflare Access add complexity (identity provider setup, login flow) for no benefit in a single-user deployment.

## Cloudflare Tunnel Setup

One-time setup, done in the Cloudflare dashboard:

1. Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel (name: `foodlog`)
2. Choose "Cloudflared" connector type
3. Copy the tunnel token (long string starting with `eyJ...`)
4. Add public hostname: `foodlog.ryanckelly.ca` → service `http://localhost:3474`
5. Paste token into `/opt/foodlog/.env` as `CLOUDFLARE_TUNNEL_TOKEN`

DNS for `foodlog.ryanckelly.ca` is automatically created by Cloudflare as a CNAME to the tunnel — no manual DNS config needed.

## Changes Required

### 1. New FastAPI auth middleware

Create `/opt/foodlog/foodlog/api/auth.py`:

```python
from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from foodlog.config import settings


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require Authorization: Bearer <token> on every request.

    If FOODLOG_AUTH_TOKEN is unset, all requests fail (fail-closed).
    """

    async def dispatch(self, request: Request, call_next):
        if not settings.foodlog_auth_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="FOODLOG_AUTH_TOKEN not configured",
            )
        header = request.headers.get("Authorization", "")
        expected = f"Bearer {settings.foodlog_auth_token}"
        if header != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
            )
        return await call_next(request)
```

Wired into `create_app()` in `foodlog/api/app.py`:
```python
app.add_middleware(BearerTokenMiddleware)
```

### 2. Config additions

Add to `foodlog/config.py`:
```python
foodlog_auth_token: str = ""
```

Add to `.env.example`:
```
FOODLOG_AUTH_TOKEN=generate_with_openssl_rand_hex_32
CLOUDFLARE_TUNNEL_TOKEN=paste_tunnel_token_from_cloudflare_dashboard
```

### 3. docker-compose.yml — add cloudflared service

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: foodlog-cloudflared
    network_mode: service:tailscale  # Same network namespace as foodlog
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    command: tunnel --no-autoupdate run
    restart: unless-stopped
    depends_on:
      foodlog:
        condition: service_started
```

### 4. MCP transport security — add public host

Update `_default_transport_security()` in `mcp_server/server.py`:
```python
allowed_hosts=[
    "127.0.0.1:*",
    "localhost:*",
    "[::1]:*",
    "foodlog",
    "foodlog:*",
    "foodlog.tailf67313.ts.net",
    "foodlog.tailf67313.ts.net:*",
    "foodlog.ryanckelly.ca",          # NEW
    "foodlog.ryanckelly.ca:*",        # NEW
    "testserver",
],
allowed_origins=[
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
    "https://foodlog.tailf67313.ts.net:*",
    "https://foodlog.ryanckelly.ca",  # NEW
    "https://foodlog.ryanckelly.ca:*",# NEW
],
```

### 5. Update .mcp.json

```json
{
  "mcpServers": {
    "foodlog": {
      "type": "http",
      "url": "http://localhost:3473/mcp",
      "headers": {
        "Authorization": "Bearer ${FOODLOG_AUTH_TOKEN}"
      }
    }
  }
}
```

Check whether Claude Code's `.mcp.json` supports `${VAR}` interpolation for headers. If not, paste the literal token (gitignored via `.env` pattern).

### 6. Claude Code user-scoped MCP registration

Re-register with the header:
```bash
claude mcp remove foodlog --scope user
claude mcp add --transport http --scope user foodlog http://localhost:3473/mcp \
  --header "Authorization: Bearer <token>"
```

(Check the exact CLI flag; `claude mcp add --help` will confirm.)

### 7. Claude.ai custom connector

In claude.ai → Settings → Connectors → Add custom connector:
- Name: `FoodLog`
- Remote MCP URL: `https://foodlog.ryanckelly.ca/mcp`
- Custom header: `Authorization: Bearer <token>`

## Testing

### Unit tests (new)

`tests/test_auth.py`:
- `test_request_without_token_returns_401`
- `test_request_with_wrong_token_returns_401`
- `test_request_with_valid_token_returns_200`
- `test_request_when_token_unset_returns_503`

### Existing tests (need updating)

All `tests/test_api.py` tests via `TestClient` will now fail with 401. Fix by configuring the test client fixture to always send the Authorization header, using a known test token set via monkeypatch or fixture-scoped env override.

### Smoke tests (post-deploy)

```bash
# Without token — expect 401
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3473/health
# Expected: 401

# With token — expect 200
curl -s -H "Authorization: Bearer $FOODLOG_AUTH_TOKEN" http://localhost:3473/health
# Expected: {"status":"ok","fatsecret":true,"usda":true}

# Public endpoint via Cloudflare
curl -s -H "Authorization: Bearer $FOODLOG_AUTH_TOKEN" https://foodlog.ryanckelly.ca/health
# Expected: same as above

# Public without token — still 401
curl -s -o /dev/null -w "%{http_code}\n" https://foodlog.ryanckelly.ca/health
# Expected: 401
```

### End-to-end

- Claude Code (local) can call tools after `.mcp.json` update
- Claude Android (via claude.ai connector) can call tools

## Rollback

If something breaks:
```bash
cd /opt/foodlog
docker compose down
git checkout master  # Before this milestone's branch merged
docker compose up -d
```

SQLite data at `/opt/foodlog/data/foodlog.db` is untouched by any of this.

## Security Considerations

- **Bearer token leakage:** Token lives in `.env` (chmod 600) and claude.ai connector config. Never logged or committed. Rotate via `openssl rand -hex 32` and restart if ever exposed.
- **No TLS termination at home:** Cloudflare terminates TLS at the edge. Traffic inside the tunnel to localhost:3474 is unencrypted, but that's the same physical machine.
- **Outbound-only tunnel:** No UDM Pro port forward, no home IP exposure.
- **Auth fail-closed:** If `FOODLOG_AUTH_TOKEN` is unset, middleware returns 503 on every request (better than silent passthrough).

## Success Criteria

1. `curl https://foodlog.ryanckelly.ca/health` without token returns 401.
2. `curl -H "Authorization: Bearer <token>" https://foodlog.ryanckelly.ca/health` returns `{"status":"ok",...}`.
3. Claude Code sees and can call all 6 foodlog MCP tools.
4. Claude Android (via claude.ai connector) sees and can call all 6 foodlog MCP tools.
5. Local tailnet access (`https://foodlog.tailf67313.ts.net:3473/health` + bearer) still works.
6. `docker compose ps` shows three healthy containers: `foodlog`, `foodlog-tailscale`, `foodlog-cloudflared`.
7. No new open ports on UDM Pro (verified: tunnel is outbound-only).

## Deployment Summary

1. Generate token: `openssl rand -hex 32`
2. Add to `/opt/foodlog/.env`: `FOODLOG_AUTH_TOKEN=<token>`
3. Create Cloudflare Tunnel in dashboard, copy tunnel token
4. Add to `/opt/foodlog/.env`: `CLOUDFLARE_TUNNEL_TOKEN=<token>`
5. Add public hostname in tunnel: `foodlog.ryanckelly.ca` → `http://localhost:3474`
6. Implement code changes (middleware, config, compose)
7. Update tests
8. `docker compose up -d`
9. Re-register Claude Code MCP with Authorization header
10. Add claude.ai custom connector with Authorization header
