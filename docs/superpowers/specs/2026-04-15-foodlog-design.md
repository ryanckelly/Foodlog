# Natural Language Food Logger — Design Spec

## Overview

A personal food logging system that lets the user describe meals in natural language to Claude, which uses MCP tools to search nutrition databases and log entries. The backend is a FastAPI service backed by SQLite, designed to support future frontends (dashboards, UIs) beyond the MCP interface.

## Architecture

```
Claude <-> MCP Server <-> FastAPI Service <-> FatSecret / USDA / SQLite
                              ^
                     Future Dashboard / UI
```

- **FastAPI service**: Core backend. All business logic, data access, and external API integration.
- **MCP server**: Thin HTTP client exposing FastAPI endpoints as Claude tools.
- **SQLite**: Single source of truth for all food diary entries.
- **FatSecret API**: Read-only. 2.3M food database for nutrition lookups. Two-legged OAuth 1.0 (application-only, no user auth flow).
- **USDA FoodData Central**: Read-only fallback/verification. API key auth.

Claude handles all natural language interpretation natively — no separate LLM parsing layer or Anthropic API dependency.

## Project Structure

```
foodlog/
├── foodlog/
│   ├── api/
│   │   ├── app.py            # FastAPI application + lifespan
│   │   ├── routers/
│   │   │   ├── foods.py      # Search endpoints
│   │   │   ├── entries.py    # Food diary CRUD
│   │   │   └── summary.py    # Nutrition summaries
│   │   └── dependencies.py   # Shared deps (DB sessions, API clients)
│   ├── clients/
│   │   ├── fatsecret.py      # FatSecret API client (two-legged OAuth 1.0)
│   │   └── usda.py           # USDA FoodData Central client
│   ├── db/
│   │   ├── database.py       # SQLite engine/session setup
│   │   └── models.py         # SQLAlchemy models
│   ├── models/
│   │   └── schemas.py        # Pydantic request/response models
│   ├── services/
│   │   ├── search.py         # Food search orchestration (FatSecret + USDA fallback)
│   │   ├── logging.py        # Entry creation/management
│   │   └── nutrition.py      # Summaries, aggregation
│   └── config.py             # Settings from env vars
├── mcp_server/
│   └── server.py             # MCP tools -> HTTP calls to FastAPI
├── tests/
├── .env.example
└── pyproject.toml
```

## Data Model

### `food_entries` table

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| meal_type | TEXT | breakfast, lunch, dinner, snack |
| food_name | TEXT | Human-readable name ("chicken stir fry") |
| quantity | REAL | Amount (1, 1.5, 2) |
| unit | TEXT | "serving", "cup", "g", "oz", etc. |
| weight_g | REAL | Estimated weight in grams (nullable) |
| calories | REAL | kcal |
| protein_g | REAL | |
| carbs_g | REAL | |
| fat_g | REAL | |
| fiber_g | REAL | nullable |
| sugar_g | REAL | nullable |
| sodium_mg | REAL | nullable |
| source | TEXT | "fatsecret", "usda", "manual" |
| source_id | TEXT | External food ID for reference |
| raw_input | TEXT | Original natural language from user |
| logged_at | DATETIME | When the meal was eaten (user-specified or default now) |
| created_at | DATETIME | When the record was created |

Daily summaries are computed on the fly by aggregating `food_entries` grouped by date — no separate table.

## API Endpoints

### Food Search

| Method | Path | Description |
|--------|------|-------------|
| GET | `/foods/search?q={query}` | Search FatSecret, fall back to USDA |
| GET | `/foods/{source}/{id}` | Full nutrition detail for a specific food |

### Food Entries (Diary)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/entries` | Log one or more food entries (accepts array) |
| GET | `/entries?date={date}&meal_type={type}` | List entries, default today |
| PUT | `/entries/{id}` | Update an entry |
| DELETE | `/entries/{id}` | Remove an entry |

### Summaries

| Method | Path | Description |
|--------|------|-------------|
| GET | `/summary/daily?date={date}` | Day totals broken down by meal |
| GET | `/summary/range?start={date}&end={date}` | Aggregated nutrition over date range |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service status, DB connectivity, which APIs are configured |

## MCP Server Tools

Each tool is a thin wrapper calling the FastAPI endpoints.

### `search_food`
- **Params:** `query` (string)
- **Calls:** `GET /foods/search?q={query}`
- **Claude guidance:** "Search the nutrition database for a food item. Returns matches with calories and macros per serving. Use this to find the right database match before logging."

### `log_food`
- **Params:** `entries` (array of objects: food_name, quantity, unit, weight_g, calories, protein_g, carbs_g, fat_g, meal_type, source, source_id, raw_input)
- **Calls:** `POST /entries`
- **Claude guidance:** "Log one or more food items to the diary. Use after searching to include accurate nutrition data. Include the original user description in raw_input."

### `get_entries`
- **Params:** `date` (string, optional), `meal_type` (string, optional)
- **Calls:** `GET /entries`
- **Claude guidance:** "Get food diary entries. Defaults to today. Use to show the user what they've logged or to check before adding duplicates."

### `edit_entry`
- **Params:** `entry_id` (int), fields to update
- **Calls:** `PUT /entries/{id}`
- **Claude guidance:** "Update a previously logged entry — fix quantity, swap to a better match, change meal type."

### `delete_entry`
- **Params:** `entry_id` (int)
- **Calls:** `DELETE /entries/{id}`
- **Claude guidance:** "Remove a food entry from the diary."

### `get_daily_summary`
- **Params:** `date` (string, optional)
- **Calls:** `GET /summary/daily`
- **Claude guidance:** "Get total calories, protein, carbs, and fat for a day, broken down by meal. Defaults to today."

### Tools intentionally excluded from MCP
- FatSecret OAuth setup — one-time config, not conversational
- `/foods/{source}/{id}` detail lookup — Claude uses search results directly
- Date range summaries — future dashboard concern

## External API Integration

### FatSecret Platform API
- **Auth:** Two-legged OAuth 1.0 (consumer key + secret only, no user authorization)
- **Usage:** Read-only food database search (`foods.search`, `food.get.v4`)
- **Free tier:** ~5,000 calls/day (Basic plan, US food database)
- **Registration:** platform.fatsecret.com

### USDA FoodData Central
- **Auth:** API key from api.data.gov
- **Usage:** Fallback/verification when FatSecret doesn't return confident matches
- **Rate limit:** 1,000 requests/hour
- **Endpoints:** `/foods/search`, `/food/{fdcId}`

### Fallback strategy
1. Search FatSecret first
2. If no results or FatSecret isn't configured, search USDA
3. If neither is configured, return an error indicating API keys are needed

## Configuration

### Environment Variables (`.env`)

```
FATSECRET_CONSUMER_KEY=
FATSECRET_CONSUMER_SECRET=
USDA_API_KEY=
FOODLOG_DB_PATH=~/.foodlog/foodlog.db
FOODLOG_HOST=127.0.0.1
FOODLOG_PORT=8042
```

### Python Dependencies

| Package | Purpose |
|---------|---------|
| fastapi | API framework |
| uvicorn | ASGI server |
| sqlalchemy | ORM / database |
| pydantic | Request/response models (already installed) |
| pydantic-settings | Config from env vars (already installed) |
| httpx | Async HTTP for FatSecret/USDA calls (already installed) |
| requests-oauthlib | OAuth 1.0 signing for FatSecret two-legged auth |
| mcp | MCP server SDK |

### Data Directory

`~/.foodlog/` holds:
- `foodlog.db` — SQLite database

## Key Design Decisions

1. **MCP as the primary interface, not a standalone CLI.** Claude handles natural language natively — no separate parsing layer needed. Ambiguity is resolved through conversation.
2. **FastAPI as the backend, not just MCP tools.** Enables future dashboards and UIs to use the same API without going through Claude.
3. **FatSecret read-only, no diary sync.** Eliminates three-legged OAuth complexity. Local SQLite is the single source of truth. User will build their own dashboards.
4. **SQLite for local logging.** Better than flat JSON for querying history. Single file, stdlib support, no external database to run.
5. **USDA as fallback, not primary.** FatSecret has broader coverage (branded foods, restaurant items). USDA has higher accuracy for standard reference foods. Use both.
6. **Extensible tool surface.** MCP tools can be added incrementally (batch recipe calculators, meal prep tools, etc.) as needs emerge.

## What's NOT in v1

- Image/photo analysis — text-only
- Web UI or mobile app — MCP + future dashboard only
- Meal planning or recommendations
- Apple Health / Google Fit / wearable integration
- Custom food creation — existing database entries only
- FatSecret diary write/sync

## Success Criteria

User says to Claude: "I had leftover chicken stir fry with rice for lunch, maybe a cup and a half of rice, and a glass of water"

Claude uses MCP tools to search, match, and log, then responds with:

```
Logged — Lunch, April 15

  Chicken stir fry (1 serving, ~300g)    380 kcal | 28g protein | 12g fat | 35g carbs
  White rice (1.5 cups, ~280g)           340 kcal |  6g protein |  1g fat | 74g carbs
  Water                                    0 kcal

  TOTAL                                  720 kcal | 34g protein | 13g fat | 109g carbs
```
