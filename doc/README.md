# FoodLog

## Overview

Natural language food logger with an MCP interface. Exposes:
- REST API for food diary CRUD and summaries
- MCP server (mounted at `/mcp`) for Claude Code / Claude Android

All access is via Tailscale — no public internet exposure.

## Prerequisites

- Docker and Docker Compose
- Tailscale account with an auth key
- Nutrition API keys:
  - FatSecret Client ID + Client Secret (platform.fatsecret.com)
  - USDA API key (fdc.nal.usda.gov/api-key-signup/)

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| TZ | Timezone | Yes |
| PUID | User ID for file permissions | Yes |
| PGID | Group ID for file permissions | Yes |
| FATSECRET_CONSUMER_KEY | FatSecret OAuth 2.0 Client ID | Yes |
| FATSECRET_CONSUMER_SECRET | FatSecret OAuth 2.0 Client Secret | Yes |
| USDA_API_KEY | USDA FoodData Central API key | Yes |
| FOODLOG_DB_PATH | SQLite path inside container | Yes (set in compose) |
| FOODLOG_HOST | Bind address | Yes (set in compose) |
| FOODLOG_PORT | Internal port | Yes (set in compose) |
| TS_AUTHKEY | Tailscale auth key | Yes |
| TS_HOSTNAME | Hostname on Tailscale network (default: `foodlog`) | No |

## Installation

1. Generate a Tailscale auth key at https://login.tailscale.com/admin/settings/keys
   (reusable, non-ephemeral, pre-approved)

2. Create `.env` from the template:
   ```bash
   cd /opt/foodlog
   cp .env.example .env
   # Edit .env: fill in FatSecret, USDA, and TS_AUTHKEY values
   ```

3. Ensure the data directory has the SQLite database:
   ```bash
   ls /opt/foodlog/data/foodlog.db
   ```

4. Start the stack:
   ```bash
   cd /opt/foodlog
   docker compose up -d
   ```

## Verification

Check containers are running and healthy:
```bash
docker compose ps
```

Check Tailscale has connected:
```bash
docker exec foodlog-tailscale tailscale status
```

Test from localhost:
```bash
curl http://localhost:3473/health
```

Test from another tailnet device:
```bash
curl https://foodlog.tailf67313.ts.net:3473/health
```

Both should return `{"status":"ok","fatsecret":true,"usda":true}`.

## Integration

### Claude Code (local)

The `.mcp.json` in this directory is already configured for HTTP transport to `http://localhost:3473/mcp`. User-scoped registration is set up via:
```bash
claude mcp add --transport http --scope user foodlog http://localhost:3473/mcp
```

### Claude Android (remote)

In the Claude Android app, add a custom MCP connector with URL:
```
https://foodlog.tailf67313.ts.net:3473/mcp
```

The Android device must have Tailscale installed and authenticated to the same tailnet.

### REST API

Accessible at the same base URL for future dashboards or scripts:
- `/health` — service status
- `/entries` — diary CRUD (`GET`, `POST`, `PUT /{id}`, `DELETE /{id}`)
- `/summary/daily` — day totals by meal
- `/summary/range` — aggregates over a date range
- `/foods/search?q=...` — nutrition database search

## Backup & Restore

### What to Backup
- `/opt/foodlog/.env` — secrets
- `/opt/foodlog/data/foodlog.db` — all logged meals
- `/opt/foodlog/tailscale-state/` — Tailscale device identity

### Backup Commands
```bash
tar -czf foodlog-backup-$(date +%F).tar.gz \
  -C /opt/foodlog .env data/ tailscale-state/
```

### Restore
```bash
cd /opt/foodlog
tar -xzf foodlog-backup-*.tar.gz
docker compose up -d
```

## Troubleshooting

### Tailscale won't connect
1. Check auth key hasn't expired (they default to 90 days unless reusable)
2. Check Tailscale state permissions: `ls -la /opt/foodlog/tailscale-state/`
3. View logs: `docker logs foodlog-tailscale`

### Container won't start
1. View logs: `docker logs foodlog`
2. Verify env vars are populated: `docker exec foodlog env | grep -E "FAT|USDA|FOOD"`
3. Check the data volume is mounted: `docker exec foodlog ls -la /data`

### MCP endpoint returns 404
The endpoint is at `/mcp`, not `/`. Use:
- `http://localhost:3473/mcp`
- `https://foodlog.tailf67313.ts.net:3473/mcp`

### MCP endpoint returns "Invalid Host header"
If you add a new way to reach the server (new domain, new IP), add the hostname to `_default_transport_security()` in `mcp_server/server.py`.

### FatSecret returns error code 21 "Invalid IP address"
Your source IP needs whitelisting in the FatSecret developer console. Can take up to 24 hours to propagate. USDA fallback works meanwhile.

## Maintenance

### Update containers
```bash
cd /opt/foodlog
docker compose pull
docker compose up -d
```

### Rebuild after code changes
```bash
cd /opt/foodlog
docker compose build foodlog
docker compose up -d foodlog
```

### View logs
```bash
docker logs foodlog --tail 100       # App logs
docker logs foodlog-tailscale --tail 100  # Tailscale logs
```

## Security Notes

- `NET_ADMIN` and `NET_RAW` capabilities are required by Tailscale for tunnel interface creation. Documented exception per /opt/docs/STANDARDS.md.
- The service is only accessible via Tailscale (and localhost). No public internet exposure, no open ports on the UDM Pro.
- Tailscale MagicDNS provides automatic HTTPS certificates.
- No bearer token auth — Tailscale is the auth layer.

## Rollback

If the containerized deployment breaks:
```bash
cd /opt/foodlog
docker compose down
# Run directly via Python venv
source .venv/bin/activate
python -m foodlog.api.app
```

The SQLite DB is untouched by docker-compose-down — `data/foodlog.db` persists.
