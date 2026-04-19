# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3.12 food logging service with a REST API and MCP endpoint. Application code lives in `foodlog/`: `api/` contains the FastAPI app, routers, and dependencies; `db/` contains SQLAlchemy setup and models; `models/` contains Pydantic schemas; `clients/` wraps external nutrition APIs; and `services/` holds business logic. The MCP integration is in `mcp_server/`. Tests mirror the main behavior in `tests/` with shared fixtures in `tests/conftest.py`. Deployment and operations files are at the root: `Dockerfile`, `docker-compose.yml`, `.env.example`, `serve.json`, and deployment notes under `doc/` and `docs/`.

## Build, Test, and Development Commands

Create a local development environment with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the full test suite with `pytest`. Start the API locally with `python -m foodlog.api.app`; it reads host, port, database path, and API credentials from environment variables. For containerized deployment, use `docker compose up -d`, then verify with `curl http://localhost:3473/health` or `docker compose ps`. Rebuild the app container after code changes with `docker compose build foodlog`.

## Coding Style & Naming Conventions

Use 4-space indentation, type-aware Python, and small functions that keep API, persistence, client, and service responsibilities separate. Prefer explicit imports from local packages, as existing modules do. Name test files `test_*.py`, API routers by resource (`entries.py`, `foods.py`, `summary.py`), and Pydantic/SQLAlchemy models with clear domain names. Keep configuration centralized in `foodlog/config.py` and avoid hard-coded credentials or local paths.

## Testing Guidelines

Tests use `pytest`, `pytest-asyncio`, FastAPI `TestClient`, and in-memory SQLite fixtures. Add or update tests when changing route behavior, database models, schemas, MCP tools, external client handling, or nutrition service logic. Keep tests deterministic: mock external FatSecret and USDA calls rather than relying on network access or live credentials.

## Commit & Pull Request Guidelines

Recent history uses short imperative messages, often with Conventional Commit prefixes such as `feat:`, `docs:`, and `chore:`. Follow that style, for example `feat: add daily macro summary`. Pull requests should include a concise description, test results (`pytest` output or reason not run), any environment or migration notes, and screenshots or curl examples when changing user-visible API behavior.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local or Docker runs, but do not commit real secrets. Treat `.env`, `data/foodlog.db`, and `tailscale-state/` as private runtime state. Tailscale is the intended access layer; document any new public exposure or host-header changes clearly.
