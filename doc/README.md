# FoodLog

## Overview

Natural language food logger with an MCP interface. Exposes:

- REST API for food diary CRUD and summaries
- MCP server mounted at `/mcp`
- First-party OAuth endpoints for Claude remote MCP connectors
- Public health check at `/healthz`

## Deployment Model

FoodLog runs as one Docker Compose service:

- FastAPI REST API and MCP endpoint on internal port `3474`
- First-party OAuth endpoints for Claude remote MCP connectors
- `cloudflared` outbound tunnel process
- SQLite database mounted at `/data/foodlog.db`

No Tailscale sidecar is required. No inbound router port forward is required.
Cloudflare routes `https://foodlog.ryanckelly.ca/*` to
`http://localhost:3474` inside the container.

## Prerequisites

- Docker and Docker Compose
- Cloudflare Zero Trust account with a tunnel for `foodlog.ryanckelly.ca`
- Nutrition API keys:
  - FatSecret Client ID + Client Secret from `platform.fatsecret.com`
  - USDA API key from `fdc.nal.usda.gov/api-key-signup/`

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| TZ | Timezone | Yes |
| PUID | User ID for file permissions | Yes |
| PGID | Group ID for file permissions | Yes |
| FATSECRET_CONSUMER_KEY | FatSecret OAuth 2.0 Client ID | Yes |
| FATSECRET_CONSUMER_SECRET | FatSecret OAuth 2.0 Client Secret | Yes |
| USDA_API_KEY | USDA FoodData Central API key | Yes |
| FOODLOG_DB_PATH | SQLite path inside container | Yes, set in compose |
| FOODLOG_HOST | Bind address | Yes, set in compose |
| FOODLOG_PORT | Internal port | Yes, set in compose |
| FOODLOG_PUBLIC_BASE_URL | Public HTTPS origin, e.g. `https://foodlog.ryanckelly.ca` | Yes |
| FOODLOG_OAUTH_LOGIN_SECRET | Single-user secret for OAuth consent page | Yes |
| CLOUDFLARE_TUNNEL_TOKEN | Token from Cloudflare Tunnel setup | Yes |

## Installation

1. Create a Cloudflare tunnel:
   - Name: `foodlog`
   - Public hostname: `foodlog.ryanckelly.ca`
   - Service: `http://localhost:3474`

2. Create `.env` from the template:

   ```bash
   cd /opt/foodlog
   cp .env.example .env
   openssl rand -hex 32
   nano .env
   chmod 600 .env
   ```

   Fill in FatSecret, USDA, `FOODLOG_PUBLIC_BASE_URL`,
   `FOODLOG_OAUTH_LOGIN_SECRET`, and `CLOUDFLARE_TUNNEL_TOKEN`.

3. Ensure the data directory has the SQLite database:

   ```bash
   ls /opt/foodlog/data/foodlog.db
   ```

4. Start the stack:

   ```bash
   cd /opt/foodlog
   docker compose up -d --build
   ```

## Verification

Check the container is running and healthy:

```bash
docker compose ps
docker logs foodlog --tail 50
```

Test from localhost:

```bash
curl http://127.0.0.1:3474/healthz
```

Test the public tunnel:

```bash
curl https://foodlog.ryanckelly.ca/healthz
```

Both should return:

```json
{"status":"ok"}
```

Unauthenticated MCP should return an OAuth challenge:

```bash
curl -i -s -X POST https://foodlog.ryanckelly.ca/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  | head -20
```

Expected: `401` with `WWW-Authenticate` and `resource_metadata`.

## Integration

### Claude Web and Android

Add the connector on Claude web or Claude Desktop:

- Name: `FoodLog`
- URL: `https://foodlog.ryanckelly.ca/mcp`

Claude will run the OAuth flow. Use `FOODLOG_OAUTH_LOGIN_SECRET` on the FoodLog
consent page. After the connector is connected, Claude Android can use it from
the same Claude account.

### REST API

The REST API is available at the same origin and is protected by OAuth bearer
tokens:

- `/entries` - diary CRUD with `GET`, `POST`, `PUT /{id}`, and `DELETE /{id}`
- `/summary/daily` - day totals by meal
- `/summary/range` - aggregates over a date range
- `/foods/search?q=...` - nutrition database search

Future dashboards should use the HTTP API rather than opening the SQLite file
directly. A dashboard running on this host can make server-side calls to
`http://127.0.0.1:3474`; a dashboard accessed from other LAN devices should
proxy API calls through its own backend or use the public OAuth-protected API.

## Backup & Restore

### What to Backup

- `/opt/foodlog/.env` - secrets
- `/opt/foodlog/data/foodlog.db` - all logged meals and OAuth state

### Backup Commands

```bash
tar -czf foodlog-backup-$(date +%F).tar.gz \
  -C /opt/foodlog .env data/
```

### Restore

```bash
cd /opt/foodlog
tar -xzf foodlog-backup-*.tar.gz
docker compose up -d --build
```

## Troubleshooting

### Tunnel not connected

1. View logs: `docker logs foodlog --tail 100`
2. Confirm `CLOUDFLARE_TUNNEL_TOKEN` is set in `.env`.
3. Confirm the Cloudflare tunnel service target is `http://localhost:3474`.

### Container won't start

1. View logs: `docker logs foodlog --tail 100`
2. Verify env vars are populated: `docker exec foodlog env | grep -E "FAT|USDA|FOOD|CLOUDFLARE|TUNNEL"`
3. Check the data volume is mounted: `docker exec foodlog ls -la /data`

### OAuth fails before consent

`FOODLOG_PUBLIC_BASE_URL` must exactly match the public origin, including
`https://` and excluding a trailing slash.

### Consent rejects the secret

Verify `.env` has the exact `FOODLOG_OAUTH_LOGIN_SECRET` value you paste into
the consent page.

### MCP endpoint returns "Invalid Host header"

If you add a new public hostname, add it to `_default_transport_security()` in
`mcp_server/server.py`.

### FatSecret returns error code 21 "Invalid IP address"

Your source IP needs whitelisting in the FatSecret developer console. USDA
fallback works meanwhile.

## Maintenance

### Rebuild after code changes

```bash
cd /opt/foodlog
docker compose build foodlog
docker compose up -d foodlog
```

### View logs

```bash
docker logs foodlog --tail 100
```

## Security Notes

- Cloudflare Tunnel makes an outbound-only connection; no inbound router port
  forward is required.
- The Compose port binding is localhost-only: `127.0.0.1:3474:3474`.
- `/healthz` is public. REST and MCP access require OAuth bearer tokens.
- Do not commit `.env` or `data/foodlog.db`.

## Rollback

If the containerized deployment breaks:

```bash
cd /opt/foodlog
docker compose down
git checkout <previous-working-commit>
docker compose up -d --build
```

The SQLite DB is untouched by `docker compose down`; `data/foodlog.db` persists.
