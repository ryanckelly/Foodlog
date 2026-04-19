# FoodLog Cloudflare OAuth Deployment - Design Spec

## Status

This spec supersedes the earlier Cloudflare Tunnel design from 2026-04-16.
The older design kept the Tailscale sidecar and relied on a static bearer token
configured in Claude. The revised design removes Tailscale from the deployment
path and uses OAuth because Claude remote MCP connectors do not support
user-pasted static bearer tokens as the primary connector auth mechanism.

## Overview

Expose FoodLog's remote MCP endpoint to Claude web and Claude Android through a
Cloudflare Tunnel. The service remains hosted on this machine, with no inbound
router port forwards and no dependency on Tailscale. Cloudflare provides public
HTTPS reachability; FoodLog provides first-party OAuth for connector
authentication.

The deployment is a single Docker Compose service and a single runtime
container. That container runs the FastAPI app and `cloudflared`, and persists
SQLite data under `/data`.

## Goals

- Claude Android can use FoodLog MCP tools through a custom connector that was
  configured on Claude web or Claude Desktop.
- Anthropic servers can reach the MCP endpoint over public HTTPS.
- No Tailscale auth key, Tailscale sidecar, Tailscale state directory, or
  Tailscale health dependency remains in the deployment.
- No UDM Pro inbound port forward is required.
- FoodLog data and OAuth state survive container rebuilds and restarts.
- Future local dashboards access FoodLog through HTTP APIs, not by treating the
  SQLite file as a shared database service.

## Non-Goals

- Building the dashboard now.
- Migrating SQLite to Postgres now.
- Publishing FoodLog to the Claude connector directory.
- Supporting multiple FoodLog users.
- Using Cloudflare Access as the main connector auth layer. It can protect human
  browser access, but Claude's MCP connector still needs OAuth-compatible auth.
- Keeping remote access through Tailscale.

## Architecture

```text
Claude web / Claude Android
    |
    | HTTPS
    v
Cloudflare Edge
    |
    | outbound Cloudflare Tunnel
    v
foodlog container
    |-- cloudflared process
    |-- FastAPI app on 0.0.0.0:3474
    |   |-- /mcp
    |   |-- /.well-known/oauth-protected-resource/mcp
    |   |-- /.well-known/oauth-authorization-server
    |   |-- /authorize
    |   |-- /token
    |   |-- /register
    |   |-- /revoke
    |   |-- /healthz
    |   `-- existing REST API routes
    `-- /data/foodlog.db
```

Cloudflare routes:

```text
https://foodlog.ryanckelly.ca/* -> http://127.0.0.1:3474/*
```

The app still binds to `0.0.0.0` inside the container so Docker can publish a
host-local debugging port if desired. Compose should publish that port only to
`127.0.0.1`, not the LAN:

```yaml
ports:
  - "127.0.0.1:3474:3474"
```

This keeps the public path through Cloudflare while allowing local curl and
future same-host dashboard development.

## Container Model

The Docker image includes:

- Python 3.12 runtime and the FoodLog package.
- `cloudflared`.
- An entrypoint script that starts both long-running processes.

The entrypoint:

1. Verifies required environment variables are present.
2. Starts `cloudflared tunnel --no-autoupdate run` using the `TUNNEL_TOKEN`
   environment variable, so the tunnel token does not appear in process
   arguments.
3. Starts `python -m foodlog.api.app`.
4. Forwards termination signals to both processes.
5. Exits if either process exits, letting Docker's restart policy recover the
   container.

Compose contains only the `foodlog` service for this deployment. A future
dashboard service can be added to the same Compose project without changing the
database ownership model.

## Public Surface

Unauthenticated public routes:

- `GET /healthz`: minimal liveness check, returns no credential status or food
  data.
- OAuth discovery and flow routes:
  - `GET /.well-known/oauth-protected-resource/mcp`
  - `GET /.well-known/oauth-authorization-server`
  - `POST /register`
  - `GET /authorize`
  - `GET /oauth/consent`
  - `POST /oauth/consent`
  - `POST /token`
  - `POST /revoke`

Protected public routes:

- `POST /mcp` and any other MCP transport routes.
- Existing FoodLog REST data routes such as entries, foods, and summaries.

The existing `/health` route becomes protected. Deployment smoke tests use
`/healthz`, because `/health` reveals external provider configuration state.

## OAuth Model

FoodLog acts as both:

- OAuth resource server for `/mcp`.
- OAuth authorization server for this single-user deployment.

The implementation uses the MCP Python SDK auth primitives for the MCP resource
server:

- `AuthSettings` advertises `issuer_url` and `resource_server_url`.
- The resource server URL is `https://foodlog.ryanckelly.ca/mcp`.
- The protected resource metadata URL is therefore
  `https://foodlog.ryanckelly.ca/.well-known/oauth-protected-resource/mcp`.
- A FoodLog `TokenVerifier` validates access tokens from SQLite.
- A FoodLog OAuth provider implements dynamic client registration,
  authorization code exchange, refresh, and revocation.

Because MCP OAuth discovery routes must be available at the public origin, the
FastMCP ASGI app must not be mounted only under `/mcp` with all of its internal
routes hidden below that prefix. The app composition exposes the MCP route at
`/mcp` and OAuth metadata/auth routes at the origin root. The implementation
configures FastMCP with `streamable_http_path="/mcp"` and composes its Starlette
routes into the top-level ASGI app after the existing FastAPI REST routes.

## User Auth Flow

Setup and reconnect are done through Claude web or Claude Desktop. Claude
Android uses connectors that are already configured on the Claude account.

1. User adds a custom connector in Claude web:
   `https://foodlog.ryanckelly.ca/mcp`.
2. Claude connects to `/mcp`.
3. FoodLog returns `401 Unauthorized` with a `WWW-Authenticate` header pointing
   to protected resource metadata.
4. Claude discovers FoodLog's authorization server metadata.
5. Claude dynamically registers an OAuth client through `/register`.
6. Claude redirects the user's browser to `/authorize`.
7. FoodLog records the pending authorization request and redirects the browser
   to `/oauth/consent`.
8. FoodLog shows a small consent page with:
   - Connector/client name.
   - Requested scopes.
   - A single password/secret field.
   - An authorize button.
9. User enters the FoodLog OAuth login secret from the local secret store.
10. FoodLog creates a short-lived authorization code and redirects to Claude's
   callback URL.
11. Claude exchanges the code for access and refresh tokens at `/token`.
12. Claude sends `Authorization: Bearer <access-token>` on each MCP request.

The login secret is not sent to Claude. It is submitted only to FoodLog's
`/oauth/consent` form over Cloudflare HTTPS.

## OAuth Secrets and Storage

Environment variables:

- `CLOUDFLARE_TUNNEL_TOKEN`: remotely managed Cloudflare Tunnel token.
- `FOODLOG_PUBLIC_BASE_URL`: `https://foodlog.ryanckelly.ca`.
- `FOODLOG_OAUTH_LOGIN_SECRET`: high-entropy single-user secret for the consent
  form.
- `FOODLOG_DB_PATH`: `/data/foodlog.db`.
- Existing nutrition API credentials.

OAuth state lives in SQLite alongside FoodLog data:

- Registered OAuth clients.
- Pending authorization requests.
- Authorization codes.
- Access token hashes.
- Refresh token hashes.
- Token revocation timestamps.

Tokens are opaque random values. FoodLog stores only token hashes. Authorization
codes are single-use and expire quickly.

Recommended token lifetimes:

- Authorization code: 5 minutes.
- Access token: 1 hour.
- Refresh token: 90 days.

Refresh tokens rotate on use. Reauthentication is required when the refresh
token expires, is revoked, the connector is removed, OAuth state is lost, the
public hostname changes, or the requested scopes change.

## Scopes

Initial scopes:

- `foodlog.read`: allows `search_food`, `get_entries`, and
  `get_daily_summary`.
- `foodlog.write`: allows `log_food`, `edit_entry`, and `delete_entry`.

The first connector approval should request both scopes because the expected
Claude workflow includes logging and correcting food entries. The tool layer
should enforce scopes so read-only access can be supported later without
reworking the OAuth model.

## Client Registration Rules

Dynamic Client Registration is enabled because Claude supports it and it avoids
manual client ID setup.

Registration policy:

- Accept public OAuth clients using PKCE.
- Support `authorization_code` and `refresh_token` grants.
- Support `token_endpoint_auth_method` of `none`.
- Store each registered client in SQLite.
- Validate redirect URIs exactly during authorization, except for the explicit
  Claude Code loopback rule below.
- Allow Claude hosted callback:
  `https://claude.ai/api/mcp/auth_callback`.
- Allow Claude Code loopback callbacks:
  `http://localhost:<port>/callback` and
  `http://127.0.0.1:<port>/callback`, with port-agnostic matching for those two
  loopback hosts.
- Reject non-HTTPS non-loopback redirect URIs.

## Dashboard Extension Path

Do not create a database container for SQLite. SQLite is a file owned by the
FoodLog app, not a network database service.

Future dashboard access should use HTTP APIs:

```text
browser on LAN
    -> dashboard service
    -> http://foodlog:3474/dashboard/...
    -> FoodLog app
    -> /data/foodlog.db
```

The dashboard backend can be added as a second Compose service later. It should
call FoodLog API endpoints over the private Compose network using a server-side
read token. The browser should not receive that token.

For quick local experimentation, a dashboard may mount `./data:/data:ro` and
read `/data/foodlog.db` directly. That is acceptable only for read-only local
prototypes. If multiple services need first-class SQL access, migrate to
Postgres instead of inventing a SQLite database container.

## Error Handling

- Missing `CLOUDFLARE_TUNNEL_TOKEN`: container startup fails.
- Missing `FOODLOG_OAUTH_LOGIN_SECRET`: container startup fails.
- Missing or malformed `FOODLOG_PUBLIC_BASE_URL`: container startup fails.
- `cloudflared` exits: entrypoint exits and Docker restarts the container.
- FastAPI exits: entrypoint stops `cloudflared` and exits.
- Unauthenticated MCP request: `401` with `WWW-Authenticate` and protected
  resource metadata URL.
- Invalid or expired access token: `401`.
- Valid token missing required scope: `403`.
- Expired or already-used authorization code: OAuth error response from
  `/token`.
- Expired refresh token: OAuth `invalid_grant`; Claude prompts reconnect.
- SQLite unavailable or corrupted: app startup fails with a clear log message.

## Testing Strategy

Unit tests:

- OAuth token hash creation and verification.
- Authorization code expiry and one-time use.
- Refresh token rotation.
- Redirect URI validation.
- Scope enforcement by tool.
- `TokenVerifier` returns valid access metadata for active tokens and rejects
  expired, revoked, or wrong-resource tokens.

Integration tests:

- `GET /.well-known/oauth-protected-resource/mcp` returns metadata for
  `https://foodlog.ryanckelly.ca/mcp`.
- `GET /.well-known/oauth-authorization-server` returns OAuth endpoint metadata.
- Unauthenticated `/mcp` request returns `401` and a `WWW-Authenticate` header
  with the resource metadata URL.
- OAuth authorization code flow succeeds with the configured login secret.
- `/mcp` accepts a valid access token and rejects missing, expired, or
  insufficient-scope tokens.
- Existing REST API tests continue to pass with test auth helpers.

Deployment smoke tests:

- `docker compose config` validates.
- `docker compose up -d --build` starts one `foodlog` container.
- `docker logs foodlog` shows app startup and Cloudflare tunnel registration.
- `curl https://foodlog.ryanckelly.ca/healthz` returns `{"status":"ok"}`.
- `curl -X POST https://foodlog.ryanckelly.ca/mcp` without auth returns `401`
  with OAuth metadata.
- MCP Inspector or Claude connector setup completes OAuth and lists all FoodLog
  tools.
- Claude Android can call `get_daily_summary` after the connector is connected
  through Claude web.

## Deployment Steps

1. Generate `FOODLOG_OAUTH_LOGIN_SECRET`.
2. Create a Cloudflare Tunnel named `foodlog`.
3. Configure public hostname:
   `foodlog.ryanckelly.ca` -> `http://localhost:3474`.
4. Add `CLOUDFLARE_TUNNEL_TOKEN`, `FOODLOG_PUBLIC_BASE_URL`, and
   `FOODLOG_OAUTH_LOGIN_SECRET` to `/opt/foodlog/.env`.
5. Rebuild and start the single-container Compose service.
6. Open Claude web and add the custom connector URL:
   `https://foodlog.ryanckelly.ca/mcp`.
7. Complete the FoodLog OAuth consent flow.
8. Enable the connector in Claude Android and test "What did I eat today?"

## Rollback

Rollback preserves SQLite data as long as `/opt/foodlog/data/foodlog.db` remains
mounted under `/data`.

If the new deployment fails:

1. `docker compose down`.
2. Checkout the previous working commit or branch.
3. Restore the previous Compose file.
4. Restart the prior deployment.

The Cloudflare Tunnel can remain configured but inactive while the container is
stopped.

## Security Notes

- The service is public only through Cloudflare Tunnel; no router port forward
  is required.
- OAuth is the only remote MCP authentication mechanism.
- Static bearer tokens are not used for Claude connector auth.
- Refresh tokens are rotated and stored only as hashes.
- Access tokens are short-lived and bound to the FoodLog MCP resource.
- The consent page must use constant-time comparison for the login secret.
- The login secret should be high entropy and stored only in `.env`.
- Project-scoped `.mcp.json` must not contain secrets.
- Future dashboard tokens must stay server-side and must not be sent to the
  browser.

## References

- Claude custom connector network behavior: remote connectors originate from
  Anthropic infrastructure, not the local device.
- Claude connector auth support: OAuth and authless are supported; user-pasted
  static bearer tokens are not supported.
- MCP authorization spec 2025-06-18: protected MCP servers act as OAuth resource
  servers, advertise protected resource metadata, and require OAuth bearer
  tokens on protected requests.
- MCP Python SDK authorization docs: `AuthSettings`, `TokenVerifier`, and
  OAuth protected resource metadata support.
- Cloudflare Tunnel docs: remotely managed tunnels can run with `cloudflared`
  and `TUNNEL_TOKEN` over outbound-only connections.
