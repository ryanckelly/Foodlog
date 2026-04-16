# FoodLog Tailscale Deployment — Design Spec

## Overview

Containerize foodlog and deploy it behind a Tailscale sidecar, matching the pattern used by `/opt/ollama/`. Refactor the MCP server to mount directly onto the FastAPI app (single process, single port), eliminating the HTTP indirection between MCP tools and the backend. Once deployed, the service is reachable from any authenticated tailnet device — including the Claude Android app — at `https://foodlog.tailf67313.ts.net:3473`. No public internet exposure.

## Goals

- Deploy foodlog as a docker-compose stack under `/opt/foodlog/` following the server's service conventions.
- Make the MCP server reachable over HTTPS from the Claude Android app via Tailscale.
- Simplify the codebase: one process, one port, MCP mounted on FastAPI.
- Preserve existing SQLite data across the move.

## Non-Goals

- Public internet exposure or custom domain.
- Bearer token or OAuth layer (Tailscale is the auth).
- Postgres migration — SQLite stays.
- Multi-user support.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  foodlog container  (network_mode: service:tailscale)│
│                                                      │
│  uvicorn — FastAPI app on internal port 3474        │
│                                                      │
│   /health, /entries, /summary, /foods  ← REST       │
│   /mcp  ← MCP mounted ASGI app                      │
│         ↓                                            │
│   create_mcp_server() (FastMCP)                     │
│         ↓                                            │
│   EntryService, SearchService, SummaryService       │
│     (direct Python calls, no HTTP)                  │
│         ↓                                            │
│   SQLite @ /data/foodlog.db                         │
└─────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────┐
│  foodlog-tailscale sidecar                           │
│  • serve.json: 3473 → 127.0.0.1:3474                │
│  • host port map: 3473:3474                         │
└─────────────────────────────────────────────────────┘
```

**Access URLs:**
- Tailscale: `https://foodlog.tailf67313.ts.net:3473/mcp` (and `/entries`, `/health`, etc.)
- Localhost: `http://localhost:3473/mcp`

## Directory Layout

The git repo moves wholesale from `/home/ryan/foodlog` to `/opt/foodlog`. No split brain between dev and deployed copies.

```
/opt/foodlog/
├── .env                  # FatSecret/USDA keys + TS_AUTHKEY (gitignored)
├── .env.example          # Template, includes TS_AUTHKEY placeholder
├── .gitignore            # Plus data/ and tailscale-state/
├── .mcp.json             # HTTP transport to localhost:3473/mcp
├── docker-compose.yml    # NEW — foodlog + tailscale sidecar
├── Dockerfile            # NEW — builds the foodlog image
├── serve.json            # NEW — Tailscale port forwarding 3473→3474
├── pyproject.toml        # Unchanged
├── foodlog/              # Existing Python package
├── mcp_server/           # Refactored for direct-call mode
├── tests/                # Existing
├── docs/                 # Existing specs/plans
├── data/                 # NEW — SQLite DB lives here (gitignored)
├── tailscale-state/      # NEW — Tailscale device identity (gitignored)
└── doc/
    └── README.md         # NEW — /opt-style deployment doc
```

Directory ownership: `1000:1000` per `/opt/docs/STANDARDS.md`.

## Key Refactor: MCP Tools Call Services Directly

MCP tools currently call back into FastAPI via httpx. After the refactor, they import and call services directly. The FastAPI app mounts the MCP server as an ASGI sub-app at `/mcp`.

```python
# foodlog/api/app.py
def create_app() -> FastAPI:
    app = FastAPI(title="FoodLog", version="0.1.0", lifespan=lifespan)

    # Routers (existing)
    app.include_router(entries_router)
    app.include_router(summary_router)
    app.include_router(foods_router)

    # Mount MCP
    from mcp_server.server import create_mcp_server
    mcp = create_mcp_server()
    app.mount("/mcp", mcp.streamable_http_app())

    return app
```

```python
# mcp_server/server.py (abbreviated)
from mcp.server.fastmcp import FastMCP

from foodlog.api.dependencies import (
    get_fatsecret_client,
    get_usda_client,
    get_session_factory_cached,
)
from foodlog.services.search import SearchService
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService
from foodlog.models.schemas import FoodEntryCreate, FoodEntryResponse

def create_mcp_server() -> FastMCP:
    mcp = FastMCP("FoodLog", instructions="...")

    @mcp.tool()
    async def search_food(query: str) -> list[dict]:
        svc = SearchService(
            fatsecret=get_fatsecret_client(),
            usda=get_usda_client(),
        )
        results = await svc.search(query)
        return [r.model_dump() for r in results]

    @mcp.tool()
    async def log_food(entries: list[dict]) -> list[dict]:
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            models = [FoodEntryCreate.model_validate(e) for e in entries]
            results = svc.create_many(models)
            return [
                FoodEntryResponse.model_validate(r).model_dump(mode="json")
                for r in results
            ]

    # ... get_entries, edit_entry, delete_entry, get_daily_summary ...

    return mcp
```

A new helper `get_session_factory_cached()` in `foodlog/api/dependencies.py` returns a cached session factory (singleton) so MCP tools can open short-lived sessions without depending on FastAPI's request-scoped `get_db`.

## Docker Compose

```yaml
# /opt/foodlog/docker-compose.yml
services:
  foodlog:
    build: .
    container_name: foodlog
    network_mode: service:tailscale
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
    volumes:
      - ./data:/data
    restart: unless-stopped
    depends_on:
      tailscale:
        condition: service_healthy

  tailscale:
    image: tailscale/tailscale:latest
    container_name: foodlog-tailscale
    hostname: ${TS_HOSTNAME:-foodlog}
    ports:
      - "3473:3474"
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_SERVE_CONFIG=/config/serve.json
      - TS_USERSPACE=false
    volumes:
      - ./tailscale-state:/var/lib/tailscale
      - ./serve.json:/config/serve.json:ro
    cap_add:
      - NET_ADMIN
      - NET_RAW
    devices:
      - /dev/net/tun:/dev/net/tun
    healthcheck:
      test: ["CMD", "tailscale", "status", "--json"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    restart: unless-stopped
```

## Tailscale serve.json

```json
{
  "TCP": {
    "3473": {
      "TCPForward": "127.0.0.1:3474"
    }
  }
}
```

## Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY foodlog/ ./foodlog/
COPY mcp_server/ ./mcp_server/

RUN pip install --no-cache-dir -e .

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 3474

CMD ["python", "-m", "foodlog.api.app"]
```

No multi-stage build — SQLite has no native deps, everything's pure Python.

## Auth Model

**Tailscale-only.** Matches the posture of `/opt/ollama/` (no bearer token on Ollama). If you're on the tailnet you're authenticated; if you're not, the service is unreachable. No additional secrets to manage in the Claude Android MCP config.

## Data Migration

The existing SQLite database at `~/.foodlog/foodlog.db` is copied to `/opt/foodlog/data/foodlog.db` during deployment. All previously logged entries survive the move.

## Configuration

### Environment Variables

```
# /opt/foodlog/.env (gitignored)
TZ=America/Halifax
PUID=1000
PGID=1000

# API credentials (existing)
FATSECRET_CONSUMER_KEY=...
FATSECRET_CONSUMER_SECRET=...
USDA_API_KEY=...

# Tailscale (new)
TS_AUTHKEY=tskey-auth-...
TS_HOSTNAME=foodlog
```

`.env.example` mirrors this with placeholder values per `/opt/docs/STANDARDS.md`.

## Claude Code MCP Registration

Update from stdio to HTTP transport:

```json
// /opt/foodlog/.mcp.json
{
  "mcpServers": {
    "foodlog": {
      "type": "http",
      "url": "http://localhost:3473/mcp"
    }
  }
}
```

User-scoped registration is updated via:
```bash
claude mcp remove foodlog
claude mcp add --transport http --scope user foodlog http://localhost:3473/mcp
```

## Claude Android MCP Registration

Add a custom connector in the Claude Android app pointing at:
```
https://foodlog.tailf67313.ts.net:3473/mcp
```

The phone must be on the tailnet (Tailscale app installed and authenticated). The request traverses the encrypted Tailscale tunnel — Tailscale handles SSL certificate management via MagicDNS.

## Testing

- **Unit tests (unchanged):** In-memory SQLite, no network. Continue to run via `pytest` in the dev venv.
- **MCP registration test:** `tests/test_mcp.py` verifies all 6 tools are registered on the `FastMCP` instance — still valid after the mount refactor.
- **Smoke tests (post-deploy):**
  - `curl http://localhost:3473/health` — service up
  - `curl https://foodlog.tailf67313.ts.net:3473/health` (from another tailnet device) — tailnet reachable
  - Claude Code session — confirm all 6 MCP tools appear
  - Claude Android session — confirm all 6 MCP tools appear after adding the remote connector

## Rollback Plan

If the deployment breaks:

1. `cd /opt/foodlog && docker compose down`
2. Revert `.mcp.json` to stdio transport
3. Run API directly: `cd /opt/foodlog && python -m venv .venv && source .venv/bin/activate && pip install -e . && python -m foodlog.api.app`
4. Claude Code reverts to stdio MCP subprocess (the existing working setup)

SQLite data survives a rollback since `data/foodlog.db` is file-based and untouched by the rollback.

## Success Criteria

- `docker compose ps` shows both containers healthy.
- `curl https://foodlog.tailf67313.ts.net:3473/health` from another tailnet device returns `{"status": "ok", "fatsecret": true, "usda": true}`.
- Claude Code and Claude Android both see all 6 MCP tools.
- Today's food log still accessible through the new deployment (data migration verified).
- No public internet exposure — no new port-forwards on the UDM Pro.
- No new open ports on the host other than 3473 (which only binds to localhost via the Tailscale container).

## Deployment Steps (Summary)

1. `sudo mv /home/ryan/foodlog /opt/foodlog && sudo chown -R 1000:1000 /opt/foodlog`
2. `mkdir /opt/foodlog/data && cp ~/.foodlog/foodlog.db /opt/foodlog/data/`
3. `pkill -f "python foodlog/api/app.py"` — stop the old process
4. Add Dockerfile, docker-compose.yml, serve.json (see sections above)
5. Refactor MCP server + app.py + .mcp.json (see Key Refactor section)
6. Generate Tailscale auth key, add to `.env`
7. `cd /opt/foodlog && docker compose up -d`
8. `claude mcp remove foodlog && claude mcp add --transport http --scope user foodlog http://localhost:3473/mcp`
9. Add remote MCP in Claude Android: `https://foodlog.tailf67313.ts.net:3473/mcp`
10. Verify per Success Criteria
