# FoodLog Tailscale Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy foodlog as a docker-compose stack at `/opt/foodlog/` behind a Tailscale sidecar, refactor MCP server to mount directly on FastAPI (single process), and make it reachable at `https://foodlog.tailf67313.ts.net:3473` from any tailnet device including Claude Android.

**Architecture:** One FastAPI process with REST routes under `/` and MCP mounted at `/mcp` (internal `streamable_http_path='/'`). MCP tools call the existing services layer directly via a cached session factory — no HTTP indirection. A Tailscale sidecar forwards Tailscale port 3473 to internal port 3474 via `serve.json`. Local access via `ports: "3473:3474"` on the sidecar.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, MCP Python SDK (`mcp[cli]>=1.27.0`), Docker, Docker Compose, Tailscale sidecar container

---

## File Map

| File | Responsibility |
|------|---------------|
| `/home/ryan/foodlog/` → `/opt/foodlog/` | Move entire git repo |
| `/opt/foodlog/data/foodlog.db` | Migrated SQLite database (from `~/.foodlog/foodlog.db`) |
| `/opt/foodlog/foodlog/api/dependencies.py` | Add `get_session_factory_cached()` helper |
| `/opt/foodlog/foodlog/config.py` | Update default DB path to `/data/foodlog.db` for container |
| `/opt/foodlog/mcp_server/server.py` | Refactor: tools call services directly, not via httpx |
| `/opt/foodlog/foodlog/api/app.py` | Mount MCP at `/mcp`, combine lifespans, configure allowed hosts |
| `/opt/foodlog/tests/test_mcp.py` | Update: still verify tool registration, plus test mounted endpoint |
| `/opt/foodlog/tests/test_api.py` | Add: integration test for mounted `/mcp` endpoint |
| `/opt/foodlog/.mcp.json` | Switch from stdio to HTTP transport |
| `/opt/foodlog/Dockerfile` | NEW — builds foodlog image |
| `/opt/foodlog/docker-compose.yml` | NEW — foodlog + Tailscale sidecar |
| `/opt/foodlog/serve.json` | NEW — Tailscale port forwarding 3473 → 3474 |
| `/opt/foodlog/.env.example` | Add TS_AUTHKEY, TS_HOSTNAME, update DB path |
| `/opt/foodlog/.gitignore` | Add `data/` and `tailscale-state/` |
| `/opt/foodlog/doc/README.md` | NEW — /opt-style deployment documentation |

---

### Task 1: Stop Running Services and Move Repo

**Files:**
- Move: `/home/ryan/foodlog/` → `/opt/foodlog/`
- Delete: `/home/ryan/foodlog/` (after move)

- [ ] **Step 1: Stop the running FastAPI server**

Run:
```bash
pkill -f "python foodlog/api/app.py"
sleep 2
# Verify it's stopped
curl -s -m 2 http://127.0.0.1:8042/health && echo "STILL RUNNING" || echo "STOPPED"
```
Expected: `STOPPED` (curl should fail with connection refused)

- [ ] **Step 2: Verify git state is clean before move**

Run:
```bash
cd /home/ryan/foodlog && git status
```
Expected: `nothing to commit, working tree clean` or only untracked `.venv/`, `.env`, `*.db` etc. (from `.gitignore`).

If there are uncommitted tracked changes, commit them first.

- [ ] **Step 3: Move the repo with sudo to preserve ownership**

Run:
```bash
sudo mv /home/ryan/foodlog /opt/foodlog
sudo chown -R 1000:1000 /opt/foodlog
```
Verify:
```bash
ls -la /opt/foodlog/ | head -5
```
Expected: Owner is `ryan ryan`.

- [ ] **Step 4: Create data directory and migrate SQLite**

Run:
```bash
mkdir -p /opt/foodlog/data
cp ~/.foodlog/foodlog.db /opt/foodlog/data/foodlog.db
chmod 644 /opt/foodlog/data/foodlog.db
# Verify the DB has today's entries
sqlite3 /opt/foodlog/data/foodlog.db "SELECT COUNT(*) FROM food_entries;"
```
Expected: Count >= 5 (today's logged entries).

- [ ] **Step 5: Recreate venv in new location**

The old `.venv` has hardcoded paths to `/home/ryan/foodlog/`. Recreate it:
```bash
cd /opt/foodlog
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
Expected: Successful install. Then verify:
```bash
cd /opt/foodlog && source .venv/bin/activate && pytest -v
```
Expected: All 39 tests pass.

- [ ] **Step 6: Commit the move**

Nothing new to commit yet (the move itself didn't touch tracked files), but verify the git repo still works:
```bash
cd /opt/foodlog && git log --oneline -3
```
Expected: The existing commit history is intact.

---

### Task 2: Update Config Default DB Path

**Files:**
- Modify: `/opt/foodlog/foodlog/config.py`
- Modify: `/opt/foodlog/.env.example`

The container mounts data at `/data`. Update the default path so it works both in-container and in dev (dev overrides via `.env`).

- [ ] **Step 1: Update config.py default**

Edit `/opt/foodlog/foodlog/config.py`. Change this line:
```python
    foodlog_db_path: str = str(Path.home() / ".foodlog" / "foodlog.db")
```
To:
```python
    foodlog_db_path: str = "/data/foodlog.db"
```

- [ ] **Step 2: Update .env.example**

Edit `/opt/foodlog/.env.example`. Replace contents with:
```
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

# Tailscale sidecar
TS_AUTHKEY=tskey-auth-generate_in_tailscale_admin_console
TS_HOSTNAME=foodlog
```

- [ ] **Step 3: Update dev .env to match new paths**

Edit `/opt/foodlog/.env` (not committed) to override the DB path for dev:
```
FATSECRET_CONSUMER_KEY=0f436f8183a04b50ba9d104f09201201
FATSECRET_CONSUMER_SECRET=04d232b1a70c4ff7a8dfee725c1eb2fc
USDA_API_KEY=CbYnZtQj150f6zDA9Fugvf3zY2Yipkc77zFODGBw
FOODLOG_DB_PATH=/opt/foodlog/data/foodlog.db
FOODLOG_HOST=127.0.0.1
FOODLOG_PORT=8042
TS_AUTHKEY=
TS_HOSTNAME=foodlog
TZ=America/Halifax
PUID=1000
PGID=1000
```

- [ ] **Step 4: Run tests to verify nothing broke**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest -v
```
Expected: 39 passed.

- [ ] **Step 5: Commit**

```bash
cd /opt/foodlog
git add foodlog/config.py .env.example
git commit -m "chore: update default DB path for container deployment"
```

---

### Task 3: Add Cached Session Factory Helper

**Files:**
- Modify: `/opt/foodlog/foodlog/api/dependencies.py`
- Create: `/opt/foodlog/tests/test_dependencies.py`

The MCP tools will open short-lived DB sessions directly (not via FastAPI's `Depends`). Add a cached session factory.

- [ ] **Step 1: Write failing test**

Create `/opt/foodlog/tests/test_dependencies.py`:
```python
from sqlalchemy.orm import sessionmaker

from foodlog.api.dependencies import get_session_factory_cached


def test_session_factory_cached_returns_sessionmaker():
    factory = get_session_factory_cached()
    assert isinstance(factory, sessionmaker)


def test_session_factory_cached_is_singleton():
    first = get_session_factory_cached()
    second = get_session_factory_cached()
    assert first is second
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest tests/test_dependencies.py -v
```
Expected: FAIL with `ImportError: cannot import name 'get_session_factory_cached'`.

- [ ] **Step 3: Add the helper**

Edit `/opt/foodlog/foodlog/api/dependencies.py`. Find this section near the top:
```python
_session_factory = None
_http_client: httpx.AsyncClient | None = None
```

Add a new helper below the `get_db` function:
```python
def get_session_factory_cached():
    """Return a cached sessionmaker. Used by MCP tools that open short-lived
    sessions directly, rather than going through FastAPI dependency injection."""
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory()
    return _session_factory
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest tests/test_dependencies.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /opt/foodlog
git add foodlog/api/dependencies.py tests/test_dependencies.py
git commit -m "feat: add cached session factory for MCP tools"
```

---

### Task 4: Refactor MCP Server — Tools Call Services Directly

**Files:**
- Rewrite: `/opt/foodlog/mcp_server/server.py`

Replace the HTTP-based MCP tools with direct service calls. Also configure `streamable_http_path='/'` and `transport_security` so the server can be mounted cleanly at `/mcp` and accept the Tailscale hostname.

- [ ] **Step 1: Rewrite mcp_server/server.py**

Replace the entire contents of `/opt/foodlog/mcp_server/server.py` with:

```python
import datetime

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from foodlog.api.dependencies import (
    get_fatsecret_client,
    get_session_factory_cached,
    get_usda_client,
)
from foodlog.models.schemas import (
    FoodEntryCreate,
    FoodEntryResponse,
    FoodEntryUpdate,
)
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService
from foodlog.services.search import SearchService


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
            "testserver",  # for pytest TestClient
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            "https://foodlog.tailf67313.ts.net:*",
        ],
    )


def create_mcp_server() -> FastMCP:
    """Create the MCP server with tools that call services directly.

    Uses streamable_http_path='/' so when mounted at /mcp on FastAPI,
    the endpoint URL is /mcp (not /mcp/mcp).
    """
    mcp = FastMCP(
        "FoodLog",
        instructions=(
            "Food logging assistant. Use search_food to find nutrition data, "
            "then log_food to record meals. Use get_daily_summary to show totals. "
            "Always search before logging to get accurate nutrition values."
        ),
        streamable_http_path="/",
        transport_security=_default_transport_security(),
    )

    @mcp.tool()
    async def search_food(query: str) -> list[dict]:
        """Search the nutrition database for a food item.

        Returns matches with calories and macros per serving.
        Use this to find the right database match before logging.

        Args:
            query: Food name to search for (e.g. "chicken breast", "oat milk latte")
        """
        svc = SearchService(
            fatsecret=get_fatsecret_client(),
            usda=get_usda_client(),
        )
        results = await svc.search(query)
        return [r.model_dump() for r in results]

    @mcp.tool()
    def log_food(entries: list[dict]) -> list[dict]:
        """Log one or more food items to the diary.

        Use after searching to include accurate nutrition data.
        Include the original user description in raw_input.

        Args:
            entries: Array of food entry objects. Each must include:
                meal_type (breakfast/lunch/dinner/snack), food_name, quantity,
                unit, calories, protein_g, carbs_g, fat_g, source, raw_input.
                Optional: weight_g, source_id, fiber_g, sugar_g, sodium_mg.
        """
        session_factory = get_session_factory_cached()
        models = [FoodEntryCreate.model_validate(e) for e in entries]
        with session_factory() as session:
            svc = EntryService(session)
            results = svc.create_many(models)
            return [
                FoodEntryResponse.model_validate(r).model_dump(mode="json")
                for r in results
            ]

    @mcp.tool()
    def get_entries(
        date: str | None = None, meal_type: str | None = None
    ) -> list[dict]:
        """Get food diary entries. Defaults to today.

        Use to show the user what they've logged or to check before adding duplicates.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
            meal_type: Filter by meal type (breakfast/lunch/dinner/snack)
        """
        target_date = (
            datetime.date.fromisoformat(date) if date else datetime.date.today()
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            results = svc.get_by_date(target_date, meal_type=meal_type)
            return [
                FoodEntryResponse.model_validate(r).model_dump(mode="json")
                for r in results
            ]

    @mcp.tool()
    def edit_entry(entry_id: int, updates: dict) -> dict:
        """Update a previously logged entry.

        Fix quantity, swap to a better match, change meal type.

        Args:
            entry_id: ID of the entry to update
            updates: Fields to update (e.g. {"quantity": 2.0, "calories": 495.0})
        """
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            update_model = FoodEntryUpdate.model_validate(updates)
            result = svc.update(entry_id, update_model)
            if result is None:
                raise ValueError(f"Entry {entry_id} not found")
            return FoodEntryResponse.model_validate(result).model_dump(mode="json")

    @mcp.tool()
    def delete_entry(entry_id: int) -> str:
        """Remove a food entry from the diary.

        Args:
            entry_id: ID of the entry to delete
        """
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = EntryService(session)
            if not svc.delete(entry_id):
                raise ValueError(f"Entry {entry_id} not found")
            return f"Entry {entry_id} deleted"

    @mcp.tool()
    def get_daily_summary(date: str | None = None) -> dict:
        """Get total calories, protein, carbs, and fat for a day, broken down by meal.

        Defaults to today.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
        """
        target_date = (
            datetime.date.fromisoformat(date) if date else datetime.date.today()
        )
        session_factory = get_session_factory_cached()
        with session_factory() as session:
            svc = SummaryService(session)
            result = svc.daily(target_date)
            return result.model_dump(mode="json")

    return mcp


if __name__ == "__main__":
    # Kept for legacy compatibility — running as stdio no longer used in production
    # (MCP is mounted on FastAPI). This path remains for ad-hoc debugging.
    mcp = create_mcp_server()
    mcp.run(transport="stdio")
```

- [ ] **Step 2: Run existing MCP test to verify tool registration still works**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest tests/test_mcp.py -v
```
Expected: 1 passed (`test_mcp_server_has_tools`).

- [ ] **Step 3: Run the full test suite — nothing else should have regressed**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest -v
```
Expected: 41 passed (39 original + 2 new dependency tests).

- [ ] **Step 4: Commit**

```bash
cd /opt/foodlog
git add mcp_server/server.py
git commit -m "refactor: MCP tools call services directly instead of HTTP"
```

---

### Task 5: Mount MCP on FastAPI with Combined Lifespan

**Files:**
- Modify: `/opt/foodlog/foodlog/api/app.py`
- Modify: `/opt/foodlog/tests/test_api.py` (new integration test)

- [ ] **Step 1: Write failing test for mounted MCP endpoint**

Add to the bottom of `/opt/foodlog/tests/test_api.py`:

```python
def test_mcp_endpoint_initialize(client):
    """Verify the mounted MCP endpoint responds to JSON-RPC initialize."""
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 200
    # Response is SSE-formatted (event-stream)
    assert "jsonrpc" in resp.text
    assert '"protocolVersion":"2024-11-05"' in resp.text
    assert '"serverInfo"' in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest tests/test_api.py::test_mcp_endpoint_initialize -v
```
Expected: FAIL with 404 (route not mounted yet).

- [ ] **Step 3: Rewrite app.py to mount MCP**

Replace the entire contents of `/opt/foodlog/foodlog/api/app.py` with:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from foodlog.api.dependencies import cleanup_http_client
from foodlog.config import settings
from foodlog.db.database import get_engine
from foodlog.db.models import Base
from mcp_server.server import create_mcp_server

# Create the MCP server once at module load so its session_manager is a singleton.
_mcp = create_mcp_server()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB
    engine = get_engine()
    Base.metadata.create_all(engine)

    # Start MCP session manager (required for streamable_http_app to work)
    async with _mcp.session_manager.run():
        yield

    await cleanup_http_client()


def create_app() -> FastAPI:
    app = FastAPI(title="FoodLog", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "fatsecret": settings.fatsecret_configured,
            "usda": settings.usda_configured,
        }

    from foodlog.api.routers.entries import router as entries_router
    from foodlog.api.routers.foods import router as foods_router
    from foodlog.api.routers.summary import router as summary_router

    app.include_router(entries_router)
    app.include_router(summary_router)
    app.include_router(foods_router)

    # Mount MCP at /mcp (the inner Starlette app's route is "/" due to
    # streamable_http_path="/" in create_mcp_server).
    app.mount("/mcp", _mcp.streamable_http_app())

    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=settings.foodlog_host, port=settings.foodlog_port)
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest tests/test_api.py::test_mcp_endpoint_initialize -v
```
Expected: PASS.

- [ ] **Step 5: Run the full test suite**

```bash
cd /opt/foodlog && source .venv/bin/activate && pytest -v
```
Expected: 42 passed (was 41; added 1 MCP integration test).

- [ ] **Step 6: Smoke test — start the API and verify live MCP endpoint**

```bash
cd /opt/foodlog && source .venv/bin/activate && python -m foodlog.api.app &
sleep 2
# Test health
curl -s http://127.0.0.1:8042/health
echo
# Test MCP initialize (use localhost for the Host header to satisfy transport security)
curl -s -X POST http://localhost:8042/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' \
  | head -5
# Kill server
pkill -f "python -m foodlog.api.app"
```
Expected: Health returns `{"status":"ok","fatsecret":true,"usda":true}`. MCP initialize returns an SSE response with `"serverInfo"` and `"protocolVersion":"2024-11-05"`.

- [ ] **Step 7: Commit**

```bash
cd /opt/foodlog
git add foodlog/api/app.py tests/test_api.py
git commit -m "feat: mount MCP server on FastAPI at /mcp with combined lifespan"
```

---

### Task 6: Switch Claude Code MCP Registration from stdio to HTTP

**Files:**
- Modify: `/opt/foodlog/.mcp.json`
- External: Claude Code user-scoped MCP config (via `claude mcp` CLI)

- [ ] **Step 1: Update .mcp.json (project scope)**

Replace the entire contents of `/opt/foodlog/.mcp.json` with:
```json
{
  "mcpServers": {
    "foodlog": {
      "type": "http",
      "url": "http://localhost:3473/mcp"
    }
  }
}
```

- [ ] **Step 2: Remove old user-scoped foodlog registration**

Run:
```bash
claude mcp remove foodlog --scope user
```
Expected: `Removed MCP server foodlog from user config`.

- [ ] **Step 3: Add new user-scoped HTTP registration**

Run:
```bash
claude mcp add --transport http --scope user foodlog http://localhost:3473/mcp
```
Expected: `Added HTTP MCP server foodlog with URL: http://localhost:3473/mcp to user config`.

Note: The server isn't listening on 3473 yet (that comes with Docker). The registration is a config change only — `claude mcp list` will show it as disconnected until the container is up.

- [ ] **Step 4: Commit the project-scoped config change**

```bash
cd /opt/foodlog
git add .mcp.json
git commit -m "chore: switch MCP config from stdio to HTTP transport"
```

---

### Task 7: Create Dockerfile

**Files:**
- Create: `/opt/foodlog/Dockerfile`

- [ ] **Step 1: Write Dockerfile**

Create `/opt/foodlog/Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install the package (editable mode for simplicity)
COPY pyproject.toml ./
COPY foodlog/ ./foodlog/
COPY mcp_server/ ./mcp_server/

RUN pip install --no-cache-dir -e .

# Data directory for SQLite (mounted from host via compose)
RUN mkdir -p /data
VOLUME ["/data"]

# Internal port. Tailscale serve.json forwards 3473 -> 3474.
EXPOSE 3474

CMD ["python", "-m", "foodlog.api.app"]
```

- [ ] **Step 2: Validate Dockerfile builds**

Run:
```bash
cd /opt/foodlog && docker build -t foodlog:test .
```
Expected: Build succeeds, image created. Check with:
```bash
docker images | grep foodlog
```

- [ ] **Step 3: Run the image to verify it starts**

Run:
```bash
# Run with required env vars, binding to a test port
docker run --rm -d --name foodlog-test \
  -p 13474:3474 \
  -e FOODLOG_HOST=0.0.0.0 \
  -e FOODLOG_PORT=3474 \
  -e FOODLOG_DB_PATH=/data/foodlog.db \
  -e FATSECRET_CONSUMER_KEY=test \
  -e FATSECRET_CONSUMER_SECRET=test \
  -e USDA_API_KEY=test \
  -v /tmp/foodlog-test-data:/data \
  foodlog:test

sleep 3
# Test health
curl -s http://127.0.0.1:13474/health
echo
# Stop and clean up
docker stop foodlog-test
rm -rf /tmp/foodlog-test-data
```
Expected: Health returns `{"status":"ok","fatsecret":true,"usda":true}`.

- [ ] **Step 4: Clean up test image**

```bash
docker rmi foodlog:test
```

- [ ] **Step 5: Commit**

```bash
cd /opt/foodlog
git add Dockerfile
git commit -m "feat: add Dockerfile for containerized deployment"
```

---

### Task 8: Create serve.json and docker-compose.yml

**Files:**
- Create: `/opt/foodlog/serve.json`
- Create: `/opt/foodlog/docker-compose.yml`

- [ ] **Step 1: Create serve.json**

Create `/opt/foodlog/serve.json`:
```json
{
  "TCP": {
    "3473": {
      "TCPForward": "127.0.0.1:3474"
    }
  }
}
```

- [ ] **Step 2: Create docker-compose.yml**

Create `/opt/foodlog/docker-compose.yml`:
```yaml
# FoodLog with Tailscale sidecar
# Provides secure remote access via Tailscale network only.
# Pattern matches /opt/ollama/docker-compose.yml.

services:
  foodlog:
    build: .
    container_name: foodlog
    network_mode: service:tailscale  # Share Tailscale's network namespace
    environment:
      - TZ=${TZ}
      - PUID=${PUID}
      - PGID=${PGID}
      - FATSECRET_CONSUMER_KEY=${FATSECRET_CONSUMER_KEY}
      - FATSECRET_CONSUMER_SECRET=${FATSECRET_CONSUMER_SECRET}
      - USDA_API_KEY=${USDA_API_KEY}
      - FOODLOG_DB_PATH=/data/foodlog.db
      - FOODLOG_HOST=0.0.0.0
      - FOODLOG_PORT=3474  # Internal port; Tailscale forwards 3473 -> 3474
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
      - "3473:3474"  # Local host access to foodlog API
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_SERVE_CONFIG=/config/serve.json
      - TS_USERSPACE=false
    volumes:
      - ./tailscale-state:/var/lib/tailscale
      - ./serve.json:/config/serve.json:ro
    cap_add:
      # Required for creating tunnel interface
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

- [ ] **Step 3: Validate compose syntax**

```bash
cd /opt/foodlog && docker compose config
```
Expected: Prints the parsed compose config with env vars substituted. No errors.

- [ ] **Step 4: Commit**

```bash
cd /opt/foodlog
git add serve.json docker-compose.yml
git commit -m "feat: add docker-compose with Tailscale sidecar"
```

---

### Task 9: Update .gitignore for Docker-Era Artifacts

**Files:**
- Modify: `/opt/foodlog/.gitignore`

- [ ] **Step 1: Update .gitignore**

Replace the entire contents of `/opt/foodlog/.gitignore` with:
```
# Python
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/

# Secrets and data
.env
*.db

# Docker volumes
data/
tailscale-state/
```

- [ ] **Step 2: Verify git doesn't track the volume dirs**

Run:
```bash
cd /opt/foodlog && mkdir -p tailscale-state && git status --ignored | grep -E "tailscale-state|data"
```
Expected: Both dirs show in the ignored section.

- [ ] **Step 3: Commit**

```bash
cd /opt/foodlog
git add .gitignore
git commit -m "chore: gitignore docker volume directories"
```

---

### Task 10: Write /opt-style Deployment Doc

**Files:**
- Create: `/opt/foodlog/doc/README.md`

- [ ] **Step 1: Create doc/ directory**

```bash
mkdir -p /opt/foodlog/doc
```

- [ ] **Step 2: Write doc/README.md**

Create `/opt/foodlog/doc/README.md`:
```markdown
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
```

- [ ] **Step 3: Commit**

```bash
cd /opt/foodlog
git add doc/README.md
git commit -m "docs: add deployment README for Tailscale setup"
```

---

### Task 11: Obtain Tailscale Auth Key and Populate .env

**Files:**
- Modify: `/opt/foodlog/.env`

This is a manual step — the auth key must be generated in the Tailscale admin console.

- [ ] **Step 1: Generate auth key**

In a browser, open https://login.tailscale.com/admin/settings/keys

- Click "Generate auth key..."
- Settings: Reusable, Ephemeral OFF, Pre-approved ON, Tags: none (unless you use ACL tags)
- Expiration: 90 days is fine
- Copy the generated key (starts with `tskey-auth-`)

- [ ] **Step 2: Add the key to .env**

Edit `/opt/foodlog/.env`. Ensure it contains (filling in YOUR values):
```
TZ=America/Halifax
PUID=1000
PGID=1000

FATSECRET_CONSUMER_KEY=0f436f8183a04b50ba9d104f09201201
FATSECRET_CONSUMER_SECRET=04d232b1a70c4ff7a8dfee725c1eb2fc
USDA_API_KEY=CbYnZtQj150f6zDA9Fugvf3zY2Yipkc77zFODGBw

FOODLOG_DB_PATH=/data/foodlog.db
FOODLOG_HOST=0.0.0.0
FOODLOG_PORT=3474

TS_AUTHKEY=tskey-auth-PASTE_YOUR_KEY_HERE
TS_HOSTNAME=foodlog
```

- [ ] **Step 3: Verify .env permissions**

```bash
chmod 600 /opt/foodlog/.env
ls -la /opt/foodlog/.env
```
Expected: `-rw-------  1 ryan ryan  ...`

---

### Task 12: Deploy the Stack

**Files:**
- No code changes. Running `docker compose up -d`.

- [ ] **Step 1: Bring up the stack**

```bash
cd /opt/foodlog
docker compose up -d
```
Expected output ends with:
```
 ✔ Container foodlog-tailscale  Healthy
 ✔ Container foodlog             Started
```

If the `foodlog` container starts before Tailscale is healthy, compose will wait (due to `depends_on.condition: service_healthy`).

- [ ] **Step 2: Verify containers are running**

```bash
docker compose ps
```
Expected: Both `foodlog` and `foodlog-tailscale` are `running`. The tailscale container should be `healthy`.

- [ ] **Step 3: Check logs for errors**

```bash
docker logs foodlog --tail 20
docker logs foodlog-tailscale --tail 20
```
Expected:
- `foodlog`: uvicorn startup messages, "Application startup complete", listening on 0.0.0.0:3474
- `foodlog-tailscale`: "Logged in via key", "Tailscale IP: ..."

- [ ] **Step 4: Verify Tailscale hostname**

```bash
docker exec foodlog-tailscale tailscale status --json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Self: {d[\"Self\"][\"HostName\"]} @ {d[\"Self\"][\"TailscaleIPs\"]}')"
```
Expected: `Self: foodlog @ ['100.x.x.x', 'fd7a:...']`.

---

### Task 13: Smoke-Test the Deployed Stack

**Files:**
- No code changes.

- [ ] **Step 1: Test localhost health**

```bash
curl -s http://localhost:3473/health
echo
```
Expected: `{"status":"ok","fatsecret":true,"usda":true}`.

- [ ] **Step 2: Test migrated data is accessible**

```bash
curl -s "http://localhost:3473/summary/daily?date=$(date +%F)" | python3 -m json.tool
```
Expected: Shows today's breakfast + lunch entries (the ones logged earlier).

- [ ] **Step 3: Test MCP endpoint on localhost**

```bash
curl -s -X POST http://localhost:3473/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' \
  | head -5
```
Expected: SSE response containing `"protocolVersion":"2024-11-05"` and `"serverInfo"`.

- [ ] **Step 4: Test from another tailnet device (manual)**

From your phone (or another tailnet device):
```
https://foodlog.tailf67313.ts.net:3473/health
```
Expected: Same JSON response as localhost.

If this fails, check:
```bash
docker exec foodlog-tailscale tailscale serve status
```
Should show port 3473 mapped to 127.0.0.1:3474.

- [ ] **Step 5: Verify Claude Code sees the MCP tools**

```bash
claude mcp list 2>&1 | grep foodlog
```
Expected: `foodlog: http://localhost:3473/mcp - ✓ Connected`.

---

### Task 14: Register Claude Android Connector

**Files:**
- No code changes. Manual configuration in the Claude Android app.

- [ ] **Step 1: Open Claude Android app → Settings → Connectors → Add Custom MCP Server**

- [ ] **Step 2: Enter details**

- Name: `FoodLog`
- URL: `https://foodlog.tailf67313.ts.net:3473/mcp`
- Auth: None (Tailscale is the auth layer)

- [ ] **Step 3: Verify Tailscale is running on the phone**

Open the Tailscale app on Android. Confirm connected status. If not, reconnect.

- [ ] **Step 4: Test from Claude Android**

Start a new conversation in the Claude Android app. Ask: "What did I eat today?"

Claude should invoke the `get_daily_summary` tool and return today's breakfast + lunch totals.

If it can't see the tools, check:
1. Phone has Tailscale active
2. Phone can reach `https://foodlog.tailf67313.ts.net:3473/health` in a browser
3. MCP connector URL ends with `/mcp` (not `/`)

---

## Self-Review Checklist

- [ ] All 42 unit tests pass
- [ ] Docker compose healthy, both containers up
- [ ] Localhost `/health` returns `fatsecret: true, usda: true`
- [ ] Tailscale `/health` returns the same from another device
- [ ] Today's entries visible via `/summary/daily`
- [ ] Claude Code MCP shows as `✓ Connected`
- [ ] Claude Android can see and call foodlog tools
- [ ] No new ports forwarded on UDM Pro (verified: Tailscale routes traffic, not firewall rules)

## Rollback (if needed)

If any critical issue surfaces after Task 12:

```bash
cd /opt/foodlog
docker compose down
source .venv/bin/activate
python -m foodlog.api.app &
# Revert .mcp.json to stdio, re-register Claude Code
claude mcp remove foodlog --scope user
claude mcp add --scope user foodlog -- /opt/foodlog/.venv/bin/python /opt/foodlog/mcp_server/server.py
```

`data/foodlog.db` is untouched by a compose-down; the database survives a rollback.
