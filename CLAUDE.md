# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3.12 food logging service with a REST API and MCP endpoint. Application code lives in `foodlog/`: `api/` contains the FastAPI app, routers, OAuth consent routes, and dependencies; `db/` contains SQLAlchemy setup and models; `models/` contains Pydantic schemas; `clients/` wraps external nutrition APIs; and `services/` holds business logic including OAuth persistence. The MCP integration is in `mcp_server/`. Tests mirror the main behavior in `tests/` with shared fixtures in `tests/conftest.py`. Deployment and operations files are at the root: `Dockerfile`, `docker-compose.yml`, `.env.example`, `docker-entrypoint.sh`, and deployment notes under `doc/` and `docs/`.

## Build, Test, and Development Commands

Create a local development environment with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the full test suite with `pytest`. Start the API locally with `python -m foodlog.api.app`; it reads host, port, database path, public base URL, OAuth secret, and API credentials from environment variables. For containerized deployment, use `docker compose up -d --build`, then verify with `curl http://127.0.0.1:3474/healthz`, `curl https://foodlog.ryanckelly.ca/healthz`, or `docker compose ps`. Rebuild the app container after code changes with `docker compose build foodlog`.

## Deployment, MCP Access & Dashboard

FoodLog is deployed as a single Docker Compose service. The container starts both the FastAPI/MCP app and `cloudflared`; Cloudflare Tunnel routes `https://foodlog.ryanckelly.ca/*` to `http://localhost:3474` inside the container. Do not reintroduce the old Tailscale sidecar or `serve.json` path. The FastAPI app is bound to `0.0.0.0:3474` and its port is mapped to the host (`3474:3474`) to allow local network access (e.g. `http://192.168.1.40:3474`).

Claude uses the custom MCP connector URL `https://foodlog.ryanckelly.ca/mcp`. The server provides first-party OAuth endpoints and dynamic client registration. The protected MCP resource must advertise both `foodlog.read` and `foodlog.write`; otherwise Claude will connect read-only and `log_food`, `edit_entry`, and `delete_entry` will fail. If scopes change, the Claude connector must be reconnected so Claude requests fresh scopes.

The web dashboard is served at `/dashboard`. It uses Jinja2 templates and HTMX and is gated by Google Single Sign-On (SSO). When `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FOODLOG_SESSION_SECRET_KEY`, `FOODLOG_AUTHORIZED_EMAIL`, and `FOODLOG_PUBLIC_BASE_URL` are all set, unauthenticated dashboard requests redirect to `/login` and only the single authorized email can sign in. When SSO is not configured (any required env var missing), the dashboard is open — intended for local dev only, and the app logs a startup warning. See `DASHBOARD.md` for the full flow.

## Design System

The dashboard's visual language follows the Notion-inspired design system documented in `DESIGN.md` at the repo root. Key tokens: white canvas (`#ffffff`) with warm-white sunk surface (`#f6f5f4`), `rgba(0,0,0,0.95)` text, Notion Blue (`#0075de`) as the single saturated UI accent, Inter as the only typeface. Meal colors use Notion's semantic accents (orange/green/purple/teal). When editing dashboard templates or adding new UI surfaces, reference `DESIGN.md` for typography scale, shadow system, border radii, and component patterns to stay on-system — do not introduce new accent colors or type families without updating the spec.

## Coding Style & Naming Conventions

Use 4-space indentation, type-aware Python, and small functions that keep API, persistence, client, and service responsibilities separate. Prefer explicit imports from local packages, as existing modules do. Name test files `test_*.py`, API routers by resource (`entries.py`, `foods.py`, `summary.py`), and Pydantic/SQLAlchemy models with clear domain names. Keep configuration centralized in `foodlog/config.py` and avoid hard-coded credentials or local paths.

## Testing Guidelines

Tests use `pytest`, `pytest-asyncio`, FastAPI `TestClient`, and in-memory SQLite fixtures. Add or update tests when changing route behavior, database models, schemas, MCP tools, OAuth registration/consent/token behavior, external client handling, or nutrition service logic. Keep tests deterministic: mock external FatSecret and USDA calls rather than relying on network access or live credentials.

## Commit & Pull Request Guidelines

Recent history uses short imperative messages, often with Conventional Commit prefixes such as `feat:`, `docs:`, and `chore:`. Follow that style, for example `feat: add daily macro summary`. Pull requests should include a concise description, test results (`pytest` output or reason not run), any environment or migration notes, and screenshots or curl examples when changing user-visible API behavior.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local or Docker runs, but do not commit real secrets. Treat `.env`, `data/foodlog.db`, and Cloudflare tunnel tokens as private runtime state. Only pass the tunnel token into the container as `TUNNEL_TOKEN`; `cloudflared` masks that variable in logs, but it may print arbitrary custom environment variable names. The public surface is Cloudflare Tunnel plus FoodLog OAuth; document any new public hostname, scope, or host-header change clearly.
