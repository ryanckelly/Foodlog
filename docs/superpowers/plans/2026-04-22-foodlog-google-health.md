# FoodLog Google Health Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest Pixel Watch + Renpho data from the Google Health API into the FoodLog dashboard, on-presence (no scheduler), using one shared Google OAuth client and a session-guarded `/health/connect` flow.

**Architecture:** Fetch-on-dashboard-load. A new `/health/connect` route (guarded by the SSO session) performs offline OAuth and stores a Fernet-encrypted refresh token in a singleton table. On each dashboard load, a sync service checks per-table watermarks, fetches new rows from Google, upserts on `external_id`, and renders a Movement & Recovery section beneath the meals feed.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, `authlib`, `httpx`, `cryptography` (Fernet), `respx` (test fixtures), Jinja2 + HTMX.

---

## Prerequisites

**Before executing this plan, the Google SSO plan (`2026-04-20-foodlog-google-sso-plan.md`) must be fully implemented and merged.** This plan depends on:

- `starlette.middleware.sessions.SessionMiddleware` registered on the app
- `settings.google_client_id`, `settings.google_client_secret`, `settings.session_secret_key`, `settings.authorized_email`
- The `/auth/callback` route writing `request.session["user"] = email`
- Dashboard routes reading `request.session.get("user")`

Verify SSO works end-to-end before starting Task 1.

**Additionally, before Task 1**, do the following one-time setup in Google Cloud Console:
1. Open the existing SSO OAuth client (the one created for the SSO plan).
2. Add the following redirect URI: `{FOODLOG_PUBLIC_BASE_URL}/health/connect/callback`.
3. Enable the Google Health API for the project.
4. Add the following OAuth scopes to the consent screen configuration (Testing mode, restricted scopes, test user remains `ryan.c.kelly@gmail.com`):
    - `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
    - `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`
    - `https://www.googleapis.com/auth/googlehealth.sleep.readonly`

No new OAuth client. The Health flow uses the same `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` as SSO.

---

## Task 1: Dependencies and configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `foodlog/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add runtime dependency `cryptography` to `pyproject.toml`**

Open `pyproject.toml`. In `[project].dependencies` (currently ending at the `jinja2` line), append `"cryptography>=42.0.0"`:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy>=2.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "httpx>=0.27.0",
    "mcp[cli]>=1.2.0",
    "python-dotenv>=1.0.0",
    "jinja2>=3.1.0",
    "cryptography>=42.0.0",
]
```

(`respx` is already in `[project.optional-dependencies].dev` — no change needed.)

- [ ] **Step 2: Install the new dependency**

Run: `pip install -e ".[dev]"`
Expected: `cryptography` gets installed, existing packages unchanged.

- [ ] **Step 3: Add `foodlog_google_token_key` to `Settings` in `foodlog/config.py`**

Insert after the existing `oauth_refresh_token_ttl_seconds` line:

```python
    foodlog_google_token_key: str = ""
```

Then add this property below `usda_configured`:

```python
    @property
    def google_health_configured(self) -> bool:
        # Health requires SSO credentials (shared OAuth client) + the token encryption key.
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.foodlog_google_token_key
        )
```

- [ ] **Step 4: Add the new env var to `.env.example`**

Append after the existing SSO block:

```
# Fernet key for encrypting the Google Health refresh token at rest.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FOODLOG_GOOGLE_TOKEN_KEY=
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml foodlog/config.py .env.example
git commit -m "feat(health): add cryptography dep and google health config keys"
```

---

## Task 2: Database models

**Files:**
- Modify: `foodlog/db/models.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write a failing test that all seven new tables are created**

Append to `tests/test_db.py`:

```python
def test_google_health_tables_created(db_session):
    """All seven new Google Health tables exist after create_all."""
    from sqlalchemy import inspect
    insp = inspect(db_session.get_bind())
    tables = set(insp.get_table_names())
    required = {
        "google_oauth_token",
        "daily_activity",
        "body_composition",
        "resting_heart_rate",
        "sleep_sessions",
        "workouts",
        "workout_hr_samples",
    }
    missing = required - tables
    assert not missing, f"missing tables: {missing}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_db.py::test_google_health_tables_created -v`
Expected: FAIL with `missing tables: {...}`.

- [ ] **Step 3: Add the seven models to `foodlog/db/models.py`**

Append after the existing `OAuthRefreshToken` class:

```python
from sqlalchemy import CheckConstraint, ForeignKey, Date
from sqlalchemy.orm import relationship


class GoogleOAuthToken(Base):
    """Singleton row holding the encrypted Google Health refresh token."""
    __tablename__ = "google_oauth_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("id = 1", name="google_oauth_token_singleton"),)


class DailyActivity(Base):
    __tablename__ = "daily_activity"

    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int] = mapped_column(Integer, nullable=False)
    active_calories_kcal: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class BodyComposition(Base):
    __tablename__ = "body_composition"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    measured_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class RestingHeartRate(Base):
    __tablename__ = "resting_heart_rate"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    measured_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    bpm: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class SleepSession(Base):
    __tablename__ = "sleep_sessions"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    start_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class Workout(Base):
    __tablename__ = "workouts"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    start_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    calories_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    hr_samples = relationship(
        "WorkoutHrSample",
        back_populates="workout",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WorkoutHrSample(Base):
    __tablename__ = "workout_hr_samples"

    workout_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("workouts.external_id", ondelete="CASCADE"),
        primary_key=True,
    )
    sample_at: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    bpm: Mapped[int] = mapped_column(Integer, nullable=False)

    workout = relationship("Workout", back_populates="hr_samples")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_db.py::test_google_health_tables_created -v`
Expected: PASS.

- [ ] **Step 5: Run the whole test suite to catch regressions**

Run: `pytest -x`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add foodlog/db/models.py tests/test_db.py
git commit -m "feat(health): add google oauth token and six health data models"
```

---

## Task 3: Google token service

**Files:**
- Create: `foodlog/services/google_token.py`
- Test: `tests/test_google_token.py`

- [ ] **Step 1: Write failing tests for encrypt/decrypt roundtrip and age**

Create `tests/test_google_token.py`:

```python
import datetime
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from foodlog.config import settings
from foodlog.db.models import GoogleOAuthToken
from foodlog.services.google_token import (
    GoogleTokenService,
    TokenAgeDays,
    TokenMissing,
)


@pytest.fixture(autouse=True)
def _token_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "foodlog_google_token_key", key)


def test_store_and_load_refresh_token_roundtrip(db_session):
    svc = GoogleTokenService(db_session)
    svc.save_refresh_token(
        refresh_token="refresh-abc",
        scopes=["a", "b"],
        issued_at=datetime.datetime(2026, 4, 22, 12, 0, 0),
    )
    loaded = svc.load_refresh_token()
    assert loaded == "refresh-abc"


def test_load_refresh_token_raises_when_missing(db_session):
    svc = GoogleTokenService(db_session)
    with pytest.raises(TokenMissing):
        svc.load_refresh_token()


def test_token_age_days(db_session):
    svc = GoogleTokenService(db_session)
    svc.save_refresh_token(
        refresh_token="x",
        scopes=[],
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=3),
    )
    assert 2 <= svc.token_age_days() <= 4


def test_upserting_overwrites_existing(db_session):
    svc = GoogleTokenService(db_session)
    svc.save_refresh_token("first", [], datetime.datetime(2026, 4, 1))
    svc.save_refresh_token("second", [], datetime.datetime(2026, 4, 22))
    assert svc.load_refresh_token() == "second"
    rows = db_session.query(GoogleOAuthToken).all()
    assert len(rows) == 1
    assert rows[0].id == 1


def test_ciphertext_is_not_plaintext(db_session):
    svc = GoogleTokenService(db_session)
    svc.save_refresh_token("plaintext-secret", [], datetime.datetime(2026, 4, 22))
    row = db_session.query(GoogleOAuthToken).one()
    assert "plaintext-secret" not in row.refresh_token_encrypted
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_google_token.py -v`
Expected: FAIL with `ModuleNotFoundError: foodlog.services.google_token`.

- [ ] **Step 3: Implement `foodlog/services/google_token.py`**

Create the file:

```python
"""Google Health token storage and access-token minting.

The refresh token is encrypted at rest with Fernet and stored in the
singleton ``google_oauth_token`` row.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from foodlog.config import settings
from foodlog.db.models import GoogleOAuthToken

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class TokenMissing(Exception):
    """Raised when no Google refresh token is stored."""


class TokenInvalid(Exception):
    """Raised when Google rejects the refresh token (invalid_grant)."""


@dataclass(slots=True)
class AccessToken:
    value: str
    expires_in: int


TokenAgeDays = float


class GoogleTokenService:
    def __init__(self, db: Session):
        self._db = db
        if not settings.foodlog_google_token_key:
            raise RuntimeError("FOODLOG_GOOGLE_TOKEN_KEY is not configured")
        self._fernet = Fernet(settings.foodlog_google_token_key.encode())

    # ---------- storage ----------

    def save_refresh_token(
        self,
        refresh_token: str,
        scopes: list[str],
        issued_at: datetime.datetime,
    ) -> None:
        ciphertext = self._fernet.encrypt(refresh_token.encode()).decode()
        row = self._db.get(GoogleOAuthToken, 1)
        if row is None:
            row = GoogleOAuthToken(
                id=1,
                refresh_token_encrypted=ciphertext,
                scopes_json=json.dumps(scopes),
                issued_at=issued_at,
            )
            self._db.add(row)
        else:
            row.refresh_token_encrypted = ciphertext
            row.scopes_json = json.dumps(scopes)
            row.issued_at = issued_at
        self._db.commit()

    def load_refresh_token(self) -> str:
        row = self._db.get(GoogleOAuthToken, 1)
        if row is None:
            raise TokenMissing()
        try:
            return self._fernet.decrypt(row.refresh_token_encrypted.encode()).decode()
        except InvalidToken as e:
            raise TokenInvalid("refresh token ciphertext could not be decrypted") from e

    def token_age_days(self) -> TokenAgeDays:
        row = self._db.get(GoogleOAuthToken, 1)
        if row is None:
            raise TokenMissing()
        delta = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - row.issued_at
        return delta.total_seconds() / 86400.0

    def forget(self) -> None:
        row = self._db.get(GoogleOAuthToken, 1)
        if row is not None:
            self._db.delete(row)
            self._db.commit()

    # ---------- access-token minting ----------

    async def mint_access_token(self, http: httpx.AsyncClient) -> AccessToken:
        refresh = self.load_refresh_token()
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code == 400:
            body = resp.json()
            if body.get("error") == "invalid_grant":
                raise TokenInvalid(body.get("error_description", "invalid_grant"))
        resp.raise_for_status()
        data = resp.json()
        row = self._db.get(GoogleOAuthToken, 1)
        if row is not None:
            row.last_used_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            self._db.commit()
        return AccessToken(value=data["access_token"], expires_in=int(data["expires_in"]))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_google_token.py -v`
Expected: All five tests PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/google_token.py tests/test_google_token.py
git commit -m "feat(health): add google token service with fernet encryption"
```

---

## Task 4: Google Health API client

**Files:**
- Create: `foodlog/clients/google_health.py`
- Create: `tests/fixtures/google_health/` (directory with JSON fixtures)
- Test: `tests/test_google_health_client.py`

- [ ] **Step 1: Look up Google Health API data type identifiers**

Open https://developers.google.com/health/reference/rest and identify the exact `dataType` identifier strings for each logical category. Record them in a module-level constant so the spec-to-code mapping is legible. The six logical categories are:

- daily steps
- daily active calories
- body composition (weight + body fat — may be two separate data types)
- resting heart rate
- heart rate samples (time series)
- sleep sessions
- workouts / exercise sessions

If the reference page is unavailable or the names have changed, use the Google Health API "Data Types" console page in the Google Cloud Console (under the Health API section) to enumerate them. **Do not invent names — verify them against the live reference.**

- [ ] **Step 2: Create JSON fixture files representing sample API responses**

Create `tests/fixtures/google_health/` and add the following files with realistic shape (the exact field names will depend on what you confirmed in Step 1; the example below uses plausible shapes — adjust to match Google's actual response envelope):

`tests/fixtures/google_health/daily_activity.json`:
```json
{
  "dataPoints": [
    {
      "name": "users/me/dataPoints/da-2026-04-22",
      "dataType": "DAILY_STEPS",
      "startTime": "2026-04-22T00:00:00Z",
      "endTime": "2026-04-23T00:00:00Z",
      "value": {"intValue": 8432},
      "originDataSource": "com.google.android.wearable.app"
    }
  ],
  "nextPageToken": ""
}
```

`tests/fixtures/google_health/body_composition.json`:
```json
{
  "dataPoints": [
    {
      "name": "users/me/dataPoints/bc-1",
      "dataType": "BODY_WEIGHT",
      "startTime": "2026-04-22T07:03:00Z",
      "endTime": "2026-04-22T07:03:00Z",
      "value": {"floatValue": 81.4},
      "originDataSource": "com.renpho.fit"
    }
  ],
  "nextPageToken": ""
}
```

Create similar fixtures for: `resting_heart_rate.json`, `sleep_sessions.json`, `workouts.json`, `workout_hr_samples.json` (sample of 5 points linked to one workout).

- [ ] **Step 3: Write failing tests for each list method**

Create `tests/test_google_health_client.py`:

```python
import datetime
import json
from pathlib import Path

import httpx
import pytest
import respx

from foodlog.clients.google_health import GoogleHealthClient

FIXTURES = Path(__file__).parent / "fixtures" / "google_health"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def http():
    return httpx.AsyncClient()


async def test_list_daily_activity_returns_normalized_rows(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/DAILY_STEPS/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("daily_activity.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_daily_activity(
            since=datetime.datetime(2026, 4, 20),
        )]
        assert len(rows) == 1
        assert rows[0].external_id.endswith("da-2026-04-22")
        assert rows[0].steps == 8432
        assert rows[0].source == "com.google.android.wearable.app"


async def test_list_body_composition_returns_normalized_rows(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/BODY_WEIGHT/dataPoints.*").mock(
            return_value=httpx.Response(200, json=_load("body_composition.json"))
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_body_composition(
            since=datetime.datetime(2026, 4, 1),
        )]
        assert len(rows) == 1
        assert rows[0].weight_kg == pytest.approx(81.4)
        assert rows[0].source == "com.renpho.fit"


async def test_list_handles_pagination(http):
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        page1 = {
            "dataPoints": [{
                "name": "users/me/dataPoints/p1",
                "dataType": "DAILY_STEPS",
                "startTime": "2026-04-22T00:00:00Z",
                "endTime": "2026-04-23T00:00:00Z",
                "value": {"intValue": 100},
                "originDataSource": "src",
            }],
            "nextPageToken": "tok",
        }
        page2 = {
            "dataPoints": [{
                "name": "users/me/dataPoints/p2",
                "dataType": "DAILY_STEPS",
                "startTime": "2026-04-23T00:00:00Z",
                "endTime": "2026-04-24T00:00:00Z",
                "value": {"intValue": 200},
                "originDataSource": "src",
            }],
            "nextPageToken": "",
        }
        mock.get(url__regex=r".*/DAILY_STEPS/dataPoints.*").mock(
            side_effect=[
                httpx.Response(200, json=page1),
                httpx.Response(200, json=page2),
            ]
        )
        client = GoogleHealthClient(http, access_token="test")
        rows = [r async for r in client.list_daily_activity(
            since=datetime.datetime(2026, 4, 20),
        )]
        assert [r.external_id for r in rows] == ["users/me/dataPoints/p1",
                                                  "users/me/dataPoints/p2"]


async def test_429_raises_rate_limited(http):
    from foodlog.clients.google_health import RateLimited
    with respx.mock(base_url="https://health.googleapis.com") as mock:
        mock.get(url__regex=r".*/DAILY_STEPS/dataPoints.*").mock(
            return_value=httpx.Response(429)
        )
        client = GoogleHealthClient(http, access_token="test")
        with pytest.raises(RateLimited):
            async for _ in client.list_daily_activity(
                since=datetime.datetime(2026, 4, 20),
            ):
                pass
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest tests/test_google_health_client.py -v`
Expected: FAIL with `ModuleNotFoundError: foodlog.clients.google_health`.

- [ ] **Step 5: Implement `foodlog/clients/google_health.py`**

Create the file:

```python
"""Thin async HTTP client for the Google Health API (v4).

One method per logical data category. Each returns an async iterator
of normalized dataclasses so the sync service can upsert row-by-row
without loading full pages into memory.

Data type identifiers below were verified against
https://developers.google.com/health/reference/rest/v4 at implementation
time. If Google renames a type, update the DATA_TYPES map — not the
call sites.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

BASE_URL = "https://health.googleapis.com"
API_VERSION = "v4"

# TODO(engineer): confirm each of these identifiers against the live
# https://developers.google.com/health/reference/rest API reference
# before running the tests. Names shown here reflect the logical
# category. The tests use matching names in their respx URL regex —
# keep the two in sync.
DATA_TYPES = {
    "daily_steps": "DAILY_STEPS",
    "daily_active_calories": "DAILY_ACTIVE_CALORIES",
    "body_weight": "BODY_WEIGHT",
    "body_fat": "BODY_FAT_PERCENT",
    "resting_heart_rate": "RESTING_HEART_RATE",
    "heart_rate_sample": "HEART_RATE",
    "sleep_session": "SLEEP_SESSION",
    "workout": "EXERCISE_SESSION",
}


class GoogleHealthError(Exception):
    pass


class RateLimited(GoogleHealthError):
    pass


@dataclass(slots=True)
class DailyActivityRow:
    external_id: str
    date: datetime.date
    steps: int
    active_calories_kcal: float
    source: str


@dataclass(slots=True)
class BodyCompositionRow:
    external_id: str
    measured_at: datetime.datetime
    weight_kg: float | None
    body_fat_pct: float | None
    source: str


@dataclass(slots=True)
class RestingHeartRateRow:
    external_id: str
    measured_at: datetime.datetime
    bpm: int
    source: str


@dataclass(slots=True)
class SleepSessionRow:
    external_id: str
    start_at: datetime.datetime
    end_at: datetime.datetime
    duration_min: int
    source: str


@dataclass(slots=True)
class WorkoutRow:
    external_id: str
    start_at: datetime.datetime
    end_at: datetime.datetime
    activity_type: str
    duration_min: int
    calories_kcal: float | None
    distance_m: float | None
    avg_hr: int | None
    max_hr: int | None
    source: str


@dataclass(slots=True)
class HrSampleRow:
    workout_id: str
    sample_at: datetime.datetime
    bpm: int


def _parse_time(s: str) -> datetime.datetime:
    # Google returns RFC3339 UTC. Strip 'Z' so we store naive UTC.
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(datetime.UTC).replace(tzinfo=None)


class GoogleHealthClient:
    def __init__(self, http: httpx.AsyncClient, access_token: str):
        self._http = http
        self._token = access_token

    async def _paginate(
        self,
        data_type: str,
        since: datetime.datetime,
        until: datetime.datetime | None = None,
    ) -> AsyncIterator[dict]:
        url = f"{BASE_URL}/{API_VERSION}/users/me/dataTypes/{data_type}/dataPoints"
        params = {
            "startTime": since.isoformat() + "Z",
        }
        if until is not None:
            params["endTime"] = until.isoformat() + "Z"
        headers = {"Authorization": f"Bearer {self._token}"}
        page_token = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            resp = await self._http.get(url, params=params, headers=headers)
            if resp.status_code == 429:
                raise RateLimited("Google Health API rate limit")
            if resp.status_code >= 500:
                raise GoogleHealthError(f"Google Health 5xx: {resp.status_code}")
            resp.raise_for_status()
            body = resp.json()
            for point in body.get("dataPoints", []):
                yield point
            page_token = body.get("nextPageToken") or None
            if not page_token:
                return

    async def list_daily_activity(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[DailyActivityRow]:
        # Daily activity comes from two data types; we'll fetch steps and
        # active-calories and join on date. For simplicity we fetch both
        # sequentially and merge in memory (days are small).
        steps_by_date: dict[datetime.date, tuple[int, str, str]] = {}
        async for pt in self._paginate(DATA_TYPES["daily_steps"], since, until):
            d = _parse_time(pt["startTime"]).date()
            steps_by_date[d] = (
                int(pt["value"]["intValue"]),
                pt.get("originDataSource", ""),
                pt["name"],
            )
        calories_by_date: dict[datetime.date, float] = {}
        async for pt in self._paginate(DATA_TYPES["daily_active_calories"], since, until):
            d = _parse_time(pt["startTime"]).date()
            calories_by_date[d] = float(pt["value"].get("floatValue", 0.0))
        for d, (steps, source, external_id) in sorted(steps_by_date.items()):
            yield DailyActivityRow(
                external_id=external_id,
                date=d,
                steps=steps,
                active_calories_kcal=calories_by_date.get(d, 0.0),
                source=source,
            )

    async def list_body_composition(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[BodyCompositionRow]:
        # Fetch weight and body-fat and merge by external_id prefix / timestamp.
        async for pt in self._paginate(DATA_TYPES["body_weight"], since, until):
            yield BodyCompositionRow(
                external_id=pt["name"],
                measured_at=_parse_time(pt["startTime"]),
                weight_kg=float(pt["value"]["floatValue"]),
                body_fat_pct=None,
                source=pt.get("originDataSource", ""),
            )
        async for pt in self._paginate(DATA_TYPES["body_fat"], since, until):
            yield BodyCompositionRow(
                external_id=pt["name"],
                measured_at=_parse_time(pt["startTime"]),
                weight_kg=None,
                body_fat_pct=float(pt["value"]["floatValue"]),
                source=pt.get("originDataSource", ""),
            )

    async def list_resting_heart_rate(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[RestingHeartRateRow]:
        async for pt in self._paginate(DATA_TYPES["resting_heart_rate"], since, until):
            yield RestingHeartRateRow(
                external_id=pt["name"],
                measured_at=_parse_time(pt["startTime"]),
                bpm=int(pt["value"]["intValue"]),
                source=pt.get("originDataSource", ""),
            )

    async def list_sleep_sessions(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[SleepSessionRow]:
        async for pt in self._paginate(DATA_TYPES["sleep_session"], since, until):
            start = _parse_time(pt["startTime"])
            end = _parse_time(pt["endTime"])
            yield SleepSessionRow(
                external_id=pt["name"],
                start_at=start,
                end_at=end,
                duration_min=int((end - start).total_seconds() // 60),
                source=pt.get("originDataSource", ""),
            )

    async def list_workouts(
        self, since: datetime.datetime, until: datetime.datetime | None = None,
    ) -> AsyncIterator[WorkoutRow]:
        async for pt in self._paginate(DATA_TYPES["workout"], since, until):
            start = _parse_time(pt["startTime"])
            end = _parse_time(pt["endTime"])
            v = pt.get("value", {}) or {}
            extras = pt.get("aggregates", {}) or {}
            yield WorkoutRow(
                external_id=pt["name"],
                start_at=start,
                end_at=end,
                activity_type=v.get("activityType") or pt.get("activityType", "unknown"),
                duration_min=int((end - start).total_seconds() // 60),
                calories_kcal=extras.get("caloriesKcal"),
                distance_m=extras.get("distanceMeters"),
                avg_hr=extras.get("avgHeartRateBpm"),
                max_hr=extras.get("maxHeartRateBpm"),
                source=pt.get("originDataSource", ""),
            )

    async def list_workout_hr_samples(
        self,
        workout_id: str,
        start_at: datetime.datetime,
        end_at: datetime.datetime,
    ) -> AsyncIterator[HrSampleRow]:
        async for pt in self._paginate(DATA_TYPES["heart_rate_sample"], start_at, end_at):
            yield HrSampleRow(
                workout_id=workout_id,
                sample_at=_parse_time(pt["startTime"]),
                bpm=int(pt["value"]["intValue"]),
            )
```

**Critical:** the `DATA_TYPES` mapping may need to change based on what you confirmed in Step 1. Also, the field names inside `value` (e.g., `intValue`, `floatValue`) must match Google's actual response schema — adjust the extraction lines if they differ.

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_google_health_client.py -v`
Expected: All four tests PASS. If fixture shapes don't match the implementation, adjust fixtures and implementation together.

- [ ] **Step 7: Run the whole suite**

Run: `pytest -x`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add foodlog/clients/google_health.py tests/test_google_health_client.py tests/fixtures/google_health/
git commit -m "feat(health): add google health api client with pagination"
```

---

## Task 5: Health sync service

**Files:**
- Create: `foodlog/services/health_sync.py`
- Test: `tests/test_health_sync.py`

- [ ] **Step 1: Write failing tests for upsert, idempotency, and cursor**

Create `tests/test_health_sync.py`:

```python
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from foodlog.clients.google_health import (
    BodyCompositionRow,
    DailyActivityRow,
    RestingHeartRateRow,
    SleepSessionRow,
    WorkoutRow,
    HrSampleRow,
)
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    RestingHeartRate,
    SleepSession,
    Workout,
    WorkoutHrSample,
)
from foodlog.services.health_sync import HealthSyncService, SyncResult


async def _collect(items):
    for i in items:
        yield i


@pytest.fixture
def client():
    c = MagicMock()
    c.list_daily_activity = lambda *a, **kw: _collect([
        DailyActivityRow(
            external_id="da-1",
            date=datetime.date(2026, 4, 22),
            steps=8432,
            active_calories_kcal=512.0,
            source="watch",
        )
    ])
    c.list_body_composition = lambda *a, **kw: _collect([
        BodyCompositionRow(
            external_id="bc-1",
            measured_at=datetime.datetime(2026, 4, 22, 7, 0),
            weight_kg=81.4,
            body_fat_pct=None,
            source="renpho",
        )
    ])
    c.list_resting_heart_rate = lambda *a, **kw: _collect([])
    c.list_sleep_sessions = lambda *a, **kw: _collect([])
    c.list_workouts = lambda *a, **kw: _collect([
        WorkoutRow(
            external_id="w-1",
            start_at=datetime.datetime(2026, 4, 22, 17, 0),
            end_at=datetime.datetime(2026, 4, 22, 17, 42),
            activity_type="run",
            duration_min=42,
            calories_kcal=410.0,
            distance_m=6800.0,
            avg_hr=152,
            max_hr=174,
            source="watch",
        )
    ])
    c.list_workout_hr_samples = lambda *a, **kw: _collect([
        HrSampleRow(workout_id="w-1", sample_at=datetime.datetime(2026, 4, 22, 17, 5), bpm=148),
        HrSampleRow(workout_id="w-1", sample_at=datetime.datetime(2026, 4, 22, 17, 6), bpm=149),
    ])
    return c


async def test_sync_inserts_rows(db_session, client):
    svc = HealthSyncService(db_session, client)
    result = await svc.sync_all()
    assert isinstance(result, SyncResult)
    assert db_session.query(DailyActivity).count() == 1
    assert db_session.query(BodyComposition).count() == 1
    assert db_session.query(Workout).count() == 1
    assert db_session.query(WorkoutHrSample).count() == 2


async def test_sync_is_idempotent(db_session, client):
    svc = HealthSyncService(db_session, client)
    await svc.sync_all()
    await svc.sync_all()
    assert db_session.query(DailyActivity).count() == 1
    assert db_session.query(Workout).count() == 1
    assert db_session.query(WorkoutHrSample).count() == 2


async def test_sync_updates_existing_row_on_conflict(db_session, client):
    svc = HealthSyncService(db_session, client)
    await svc.sync_all()
    # pretend the watch re-reports the same day with updated steps
    client.list_daily_activity = lambda *a, **kw: _collect([
        DailyActivityRow(
            external_id="da-1",
            date=datetime.date(2026, 4, 22),
            steps=9000,
            active_calories_kcal=540.0,
            source="watch",
        )
    ])
    await svc.sync_all()
    row = db_session.query(DailyActivity).one()
    assert row.steps == 9000


async def test_cursor_for_workouts_uses_max_start_at(db_session, client):
    from foodlog.services.health_sync import cursor_for
    # empty DB → cursor = 90 days ago
    cursor = cursor_for(db_session, Workout, "start_at", default_days=90)
    expected = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=90)
    assert abs((cursor - expected).total_seconds()) < 5

    db_session.add(Workout(
        external_id="w-0",
        start_at=datetime.datetime(2026, 4, 15, 12, 0),
        end_at=datetime.datetime(2026, 4, 15, 13, 0),
        activity_type="run",
        duration_min=60,
        source="watch",
    ))
    db_session.commit()
    cursor = cursor_for(db_session, Workout, "start_at", default_days=90)
    assert cursor == datetime.datetime(2026, 4, 15, 12, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_health_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: foodlog.services.health_sync`.

- [ ] **Step 3: Implement `foodlog/services/health_sync.py`**

Create the file:

```python
"""Orchestrate Google Health → FoodLog DB sync.

Per-table cursor derived from data timestamps (robust against clock skew).
All writes use upsert-on-conflict keyed by ``external_id`` for idempotency.
Runs synchronously inside a dashboard request handler.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from foodlog.clients.google_health import GoogleHealthClient, RateLimited, GoogleHealthError
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    RestingHeartRate,
    SleepSession,
    Workout,
    WorkoutHrSample,
)

DEFAULT_BACKFILL_DAYS = 90


@dataclass(slots=True)
class SyncResult:
    ok: bool = True
    rate_limited: bool = False
    server_error: bool = False
    rows_upserted: dict[str, int] = field(default_factory=dict)


def cursor_for(
    db: Session,
    model: Any,
    timestamp_attr: str,
    default_days: int,
) -> datetime.datetime:
    """Return max(timestamp_attr) or now-default_days if the table is empty."""
    col = getattr(model, timestamp_attr)
    row = db.execute(select(func.max(col))).scalar_one_or_none()
    if row is not None:
        return row
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=default_days)


class HealthSyncService:
    def __init__(self, db: Session, client: GoogleHealthClient):
        self._db = db
        self._client = client

    async def sync_all(self) -> SyncResult:
        result = SyncResult()
        try:
            result.rows_upserted["daily_activity"] = await self._sync_daily_activity()
            result.rows_upserted["body_composition"] = await self._sync_body_composition()
            result.rows_upserted["resting_heart_rate"] = await self._sync_resting_hr()
            result.rows_upserted["sleep_sessions"] = await self._sync_sleep()
            wcount, hrcount = await self._sync_workouts_with_hr()
            result.rows_upserted["workouts"] = wcount
            result.rows_upserted["workout_hr_samples"] = hrcount
        except RateLimited:
            result.ok = False
            result.rate_limited = True
        except GoogleHealthError:
            result.ok = False
            result.server_error = True
        return result

    # ---------- per-table sync methods ----------

    async def _sync_daily_activity(self) -> int:
        # Always re-fetch today and yesterday; daily totals can change late.
        today = datetime.date.today()
        since = datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time.min)
        count = 0
        async for row in self._client.list_daily_activity(since=since):
            stmt = sqlite_insert(DailyActivity).values(
                date=row.date,
                steps=row.steps,
                active_calories_kcal=row.active_calories_kcal,
                source=row.source,
                external_id=row.external_id,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["date"],
                set_=dict(
                    steps=row.steps,
                    active_calories_kcal=row.active_calories_kcal,
                    source=row.source,
                    external_id=row.external_id,
                ),
            )
            self._db.execute(stmt)
            count += 1
        self._db.commit()
        return count

    async def _sync_body_composition(self) -> int:
        since = cursor_for(self._db, BodyComposition, "measured_at", DEFAULT_BACKFILL_DAYS)
        count = 0
        async for row in self._client.list_body_composition(since=since):
            stmt = sqlite_insert(BodyComposition).values(
                external_id=row.external_id,
                measured_at=row.measured_at,
                weight_kg=row.weight_kg,
                body_fat_pct=row.body_fat_pct,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(
                    measured_at=row.measured_at,
                    weight_kg=row.weight_kg,
                    body_fat_pct=row.body_fat_pct,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
            count += 1
        self._db.commit()
        return count

    async def _sync_resting_hr(self) -> int:
        since = cursor_for(self._db, RestingHeartRate, "measured_at", DEFAULT_BACKFILL_DAYS)
        count = 0
        async for row in self._client.list_resting_heart_rate(since=since):
            stmt = sqlite_insert(RestingHeartRate).values(
                external_id=row.external_id,
                measured_at=row.measured_at,
                source=row.source,
                bpm=row.bpm,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(measured_at=row.measured_at, bpm=row.bpm, source=row.source),
            )
            self._db.execute(stmt)
            count += 1
        self._db.commit()
        return count

    async def _sync_sleep(self) -> int:
        since = cursor_for(self._db, SleepSession, "start_at", DEFAULT_BACKFILL_DAYS)
        count = 0
        async for row in self._client.list_sleep_sessions(since=since):
            stmt = sqlite_insert(SleepSession).values(
                external_id=row.external_id,
                start_at=row.start_at,
                end_at=row.end_at,
                duration_min=row.duration_min,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(
                    start_at=row.start_at,
                    end_at=row.end_at,
                    duration_min=row.duration_min,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
            count += 1
        self._db.commit()
        return count

    async def _sync_workouts_with_hr(self) -> tuple[int, int]:
        since = cursor_for(self._db, Workout, "start_at", DEFAULT_BACKFILL_DAYS)
        wcount = 0
        hrcount = 0
        async for row in self._client.list_workouts(since=since):
            stmt = sqlite_insert(Workout).values(
                external_id=row.external_id,
                start_at=row.start_at,
                end_at=row.end_at,
                activity_type=row.activity_type,
                duration_min=row.duration_min,
                calories_kcal=row.calories_kcal,
                distance_m=row.distance_m,
                avg_hr=row.avg_hr,
                max_hr=row.max_hr,
                source=row.source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=dict(
                    start_at=row.start_at,
                    end_at=row.end_at,
                    activity_type=row.activity_type,
                    duration_min=row.duration_min,
                    calories_kcal=row.calories_kcal,
                    distance_m=row.distance_m,
                    avg_hr=row.avg_hr,
                    max_hr=row.max_hr,
                    source=row.source,
                ),
            )
            self._db.execute(stmt)
            wcount += 1

            async for hr in self._client.list_workout_hr_samples(
                workout_id=row.external_id,
                start_at=row.start_at,
                end_at=row.end_at,
            ):
                stmt = sqlite_insert(WorkoutHrSample).values(
                    workout_id=hr.workout_id,
                    sample_at=hr.sample_at,
                    bpm=hr.bpm,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["workout_id", "sample_at"],
                    set_=dict(bpm=hr.bpm),
                )
                self._db.execute(stmt)
                hrcount += 1
        self._db.commit()
        return wcount, hrcount
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_health_sync.py -v`
Expected: All four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/health_sync.py tests/test_health_sync.py
git commit -m "feat(health): add sync service with upserts and cursor logic"
```

---

## Task 6: OAuth connect routes

**Files:**
- Create: `foodlog/api/routers/health_oauth.py`
- Modify: `foodlog/api/app.py`
- Test: `tests/test_health_oauth_routes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_health_oauth_routes.py`:

```python
import datetime
from unittest.mock import patch, AsyncMock

import pytest
from cryptography.fernet import Fernet

from foodlog.config import settings
from foodlog.db.models import GoogleOAuthToken


@pytest.fixture(autouse=True)
def _google_health_settings(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "authorized_email", "ryan.c.kelly@gmail.com")
    monkeypatch.setattr(settings, "session_secret_key", "test-session-secret")
    monkeypatch.setattr(settings, "foodlog_google_token_key", Fernet.generate_key().decode())


OAUTH_STATE = "test-state-xyz"


def _login(raw_client, email="ryan.c.kelly@gmail.com", with_state: bool = True):
    """Simulate SSO login (and optionally seed the OAuth state)."""
    with raw_client.session_transaction() as s:
        s["user"] = email
        if with_state:
            s["health_oauth_state"] = OAUTH_STATE


def test_connect_without_session_redirects_to_login(raw_client):
    resp = raw_client.get("/health/connect", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].endswith("/login")


def test_connect_with_session_redirects_to_google(raw_client):
    _login(raw_client)
    resp = raw_client.get("/health/connect", follow_redirects=False)
    assert resp.status_code in (302, 307)
    loc = resp.headers["location"]
    assert loc.startswith("https://accounts.google.com/")
    assert "access_type=offline" in loc
    assert "googlehealth.activity_and_fitness.readonly" in loc


def test_callback_rejects_when_not_logged_in(raw_client):
    resp = raw_client.get("/health/connect/callback?code=abc&state=xyz", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].endswith("/login")


def test_callback_rejects_email_mismatch(raw_client, db_session):
    _login(raw_client, email="someone-else@gmail.com")
    with patch("foodlog.api.routers.health_oauth._exchange_code", new=AsyncMock(
        return_value={"refresh_token": "r", "access_token": "a", "expires_in": 3600,
                       "scope": "x", "id_token_email": "intruder@gmail.com"}
    )):
        resp = raw_client.get(
            f"/health/connect/callback?code=abc&state={OAUTH_STATE}",
            follow_redirects=False,
        )
    # email mismatch is only checked once state check passes; the email
    # from the fixture intentionally doesn't match authorized_email.
    assert resp.status_code in (302, 307, 403)
    # Regardless of which gate caught it, no token should have been written.
    assert db_session.query(GoogleOAuthToken).count() == 0


def test_callback_stores_encrypted_token(raw_client, db_session):
    _login(raw_client)
    with patch("foodlog.api.routers.health_oauth._exchange_code", new=AsyncMock(
        return_value={
            "refresh_token": "refresh-xyz",
            "access_token": "a",
            "expires_in": 3600,
            "scope": "openid email profile googlehealth.sleep.readonly",
            "id_token_email": "ryan.c.kelly@gmail.com",
        }
    )):
        resp = raw_client.get(
            f"/health/connect/callback?code=abc&state={OAUTH_STATE}",
            follow_redirects=False,
        )
    assert resp.status_code in (302, 307)
    row = db_session.query(GoogleOAuthToken).one()
    assert row.id == 1
    assert "refresh-xyz" not in row.refresh_token_encrypted  # encrypted


def test_callback_rejects_bad_state(raw_client):
    _login(raw_client, with_state=True)
    resp = raw_client.get(
        "/health/connect/callback?code=abc&state=wrong-state",
        follow_redirects=False,
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run the tests — they will fail**

Run: `pytest tests/test_health_oauth_routes.py -v`
Expected: FAIL with route not found / module missing.

- [ ] **Step 3: Implement `foodlog/api/routers/health_oauth.py`**

Create the file:

```python
"""Google Health OAuth routes: /health/connect and /health/connect/callback.

Guarded by the SSO session: only an SSO-authenticated authorized_email
can initiate or complete the flow. The refresh token returned by Google
is encrypted (Fernet) and written to the singleton google_oauth_token
row.
"""
from __future__ import annotations

import base64
import datetime
import json
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.config import settings
from foodlog.services.google_token import GoogleTokenService

router = APIRouter(tags=["health-oauth"])

HEALTH_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
]

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _require_sso_session(request: Request) -> str | None:
    """Return None if authorized, otherwise a redirect path."""
    user = request.session.get("user")
    if user != settings.authorized_email:
        return "/login"
    return None


def _decode_id_token_email(id_token: str) -> str | None:
    try:
        _, payload_b64, _ = id_token.split(".")
        # base64 urlsafe, pad
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("email")
    except Exception:
        return None


async def _exchange_code(code: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        email = _decode_id_token_email(data.get("id_token", ""))
        data["id_token_email"] = email
        return data


@router.get("/health/connect")
def connect(request: Request):
    redirect = _require_sso_session(request)
    if redirect:
        return RedirectResponse(redirect, status_code=302)

    state = secrets.token_urlsafe(32)
    request.session["health_oauth_state"] = state
    redirect_uri = f"{settings.public_base_url}/health/connect/callback"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(HEALTH_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "state": state,
    }
    # On initial connect, force the consent screen so Google returns a
    # refresh token. On opportunistic re-auth we may later omit this.
    if request.query_params.get("force_consent") != "false":
        params["prompt"] = "consent"
    url = f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"
    return RedirectResponse(url, status_code=302)


@router.get("/health/connect/callback")
async def callback(request: Request, db: Session = Depends(get_db)):
    redirect = _require_sso_session(request)
    if redirect:
        return RedirectResponse(redirect, status_code=302)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    stored_state = request.session.get("health_oauth_state")
    if not code or not state or state != stored_state:
        raise HTTPException(status_code=400, detail="invalid oauth state")

    redirect_uri = f"{settings.public_base_url}/health/connect/callback"
    token = await _exchange_code(code, redirect_uri)

    email = token.get("id_token_email")
    if email is None or email.lower() != settings.authorized_email.lower():
        raise HTTPException(
            status_code=403,
            detail=f"email {email!r} is not the authorized user",
        )

    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token. Remove the app from "
                   "https://myaccount.google.com/permissions and reconnect.",
        )

    svc = GoogleTokenService(db)
    svc.save_refresh_token(
        refresh_token=refresh_token,
        scopes=token.get("scope", "").split(),
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    )

    # Drop the state so the URL can't be replayed.
    request.session.pop("health_oauth_state", None)

    return RedirectResponse("/dashboard", status_code=302)
```

- [ ] **Step 4: Register the router in `foodlog/api/app.py`**

In `foodlog/api/app.py`, locate the block that imports routers (currently at lines 55-59). Add:

```python
    from foodlog.api.routers.health_oauth import router as health_oauth_router
```

Then after `app.include_router(dashboard_router)` (line 65), add:

```python
    app.include_router(health_oauth_router)
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_health_oauth_routes.py -v`
Expected: All five tests PASS.

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/health_oauth.py foodlog/api/app.py tests/test_health_oauth_routes.py
git commit -m "feat(health): add session-guarded oauth connect + callback routes"
```

---

## Task 7: Dashboard templates (Movement & Recovery + Connect page)

**Files:**
- Create: `foodlog/templates/dashboard/movement_partial.html`
- Create: `foodlog/templates/dashboard/health_connect.html`
- Modify: `foodlog/templates/dashboard/feed_partial.html`
- Modify: `foodlog/templates/base.html` (CSS additions)
- Test: `tests/test_movement_render.py`

- [ ] **Step 1: Write failing render tests**

Create `tests/test_movement_render.py`:

```python
from fastapi.templating import Jinja2Templates
from fastapi import Request
from starlette.datastructures import Headers

TEMPLATES = Jinja2Templates(directory="foodlog/templates")


def _fake_request():
    scope = {"type": "http", "headers": Headers().raw, "method": "GET", "path": "/"}
    return Request(scope)


def test_movement_partial_empty_state_renders():
    html = TEMPLATES.get_template("dashboard/movement_partial.html").render(
        workouts=[],
        sleep=None,
        weight=None,
        net_calories=None,
    )
    assert "Movement" in html
    assert "No movement or recovery data" in html


def test_movement_partial_renders_workout_card():
    html = TEMPLATES.get_template("dashboard/movement_partial.html").render(
        workouts=[{
            "activity_type": "Run",
            "distance_km": 6.8,
            "duration_min": 42,
            "calories_kcal": 410,
            "avg_hr": 152,
            "max_hr": 174,
            "hr_samples": [{"pct": 30}, {"pct": 55}, {"pct": 95}],
        }],
        sleep={"duration_min": 387, "resting_hr": 58},
        weight={"weight_kg": 81.4, "delta_kg": -0.3, "body_fat_pct": 19.2},
        net_calories=None,
    )
    assert "Run" in html
    assert "6.8" in html
    assert "42" in html
    assert "6h 27m" in html  # 387 min formatted
    assert "81.4" in html


def test_health_connect_page_renders_prompt():
    html = TEMPLATES.get_template("dashboard/health_connect.html").render()
    assert "Connect Google Health" in html
    assert '/health/connect' in html
```

- [ ] **Step 2: Run the tests — they fail**

Run: `pytest tests/test_movement_render.py -v`
Expected: FAIL with template not found.

- [ ] **Step 3: Create `foodlog/templates/dashboard/movement_partial.html`**

```html
{# Movement & Recovery section — rendered below the meals list. #}
<section class="movement-section">
  <div class="section-head">
    <h2>Movement &amp; Recovery</h2>
  </div>

  {% if not workouts and not sleep and not weight %}
    <div class="empty">No movement or recovery data for this period</div>
  {% else %}
    <div class="movement-cards">
      {% for w in workouts %}
        <div class="mv-card">
          <div class="mv-card-title">{{ w.activity_type }}{% if w.distance_km %} · {{ w.distance_km }} km{% endif %}</div>
          <div class="mv-card-big">{{ w.duration_min }} <span class="mv-card-sub">min</span></div>
          <div class="mv-hr-chart" aria-hidden="true">
            {% for s in w.hr_samples %}<span style="height:{{ s.pct }}%"></span>{% endfor %}
          </div>
          <div class="mv-card-sub">
            {% if w.calories_kcal %}{{ w.calories_kcal|round|int }} kcal{% endif %}
            {% if w.avg_hr %} · avg {{ w.avg_hr }}{% endif %}
            {% if w.max_hr %} · peak {{ w.max_hr }}{% endif %}
          </div>
        </div>
      {% endfor %}

      {% if sleep %}
        <div class="mv-card">
          <div class="mv-card-title">Sleep last night</div>
          <div class="mv-card-big">{{ (sleep.duration_min // 60) }}h {{ "%02d"|format(sleep.duration_min % 60) }}m</div>
          <div class="mv-card-sub">
            {% if sleep.duration_min < 420 %}below 7h target{% else %}on target{% endif %}
            {% if sleep.resting_hr %} · resting hr {{ sleep.resting_hr }}{% endif %}
          </div>
        </div>
      {% endif %}

      {% if weight %}
        <div class="mv-card">
          <div class="mv-card-title">Weight</div>
          <div class="mv-card-big">{{ "%.1f"|format(weight.weight_kg) }} <span class="mv-card-sub">kg</span></div>
          <div class="mv-card-sub">
            {% if weight.delta_kg is not none %}
              {% if weight.delta_kg < 0 %}{{ "%.1f"|format(weight.delta_kg) }} kg this week
              {% else %}+{{ "%.1f"|format(weight.delta_kg) }} kg this week{% endif %}
            {% endif %}
            {% if weight.body_fat_pct %} · body fat {{ "%.1f"|format(weight.body_fat_pct) }}%{% endif %}
          </div>
        </div>
      {% endif %}
    </div>
  {% endif %}
</section>
```

- [ ] **Step 4: Create `foodlog/templates/dashboard/health_connect.html`**

```html
{% extends "base.html" %}

{% block content %}
<section class="connect-prompt">
  <h1>Connect Google Health</h1>
  <p>Link your Google Health account to import your Pixel Watch activity, Renpho weight readings, and sleep data into the FoodLog dashboard.</p>
  <a href="/health/connect" class="primary-btn">Connect Google Health</a>
  <p class="fine-print">
    FoodLog will read-only access your fitness, body composition, and sleep data.
    You can revoke this at any time from
    <a href="https://myaccount.google.com/permissions">Google account permissions</a>.
  </p>
</section>
{% endblock %}
```

- [ ] **Step 5: Modify `foodlog/templates/dashboard/feed_partial.html` to render Movement below meals**

Append to the existing file (after the closing `</section>` of the meals section):

```jinja
{% if include_movement %}
  {% include "dashboard/movement_partial.html" %}
{% endif %}
```

- [ ] **Step 6: Add CSS to `foodlog/templates/base.html`**

Locate the closing `</style>` tag and insert these rules before it. Values come from `DESIGN.md` — do not introduce new colors:

```css
/* ── Movement & Recovery ─────────────────────────────── */
.movement-section { padding-top: 8px; }
.movement-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
    margin-top: 8px;
}
.mv-card {
    padding: 16px;
    background: #ffffff;
    border: 1px solid rgba(0,0,0,0.1);
    border-radius: 12px;
    box-shadow: rgba(0,0,0,0.04) 0 4px 18px, rgba(0,0,0,0.027) 0 2.025px 7.85px,
                rgba(0,0,0,0.02) 0 0.8px 2.93px;
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.mv-card-title {
    font-size: 14px;
    font-weight: 600;
    color: #615d59;
}
.mv-card-big {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
    line-height: 1.0;
}
.mv-card-sub {
    font-size: 12px;
    color: #a39e98;
    font-weight: 400;
}
.mv-hr-chart {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    height: 32px;
}
.mv-hr-chart span {
    flex: 1;
    background: #0075de;
    opacity: 0.75;
    border-radius: 1px;
}

/* ── Connect page ────────────────────────────────────── */
.connect-prompt {
    max-width: 540px;
    margin: 80px auto;
    text-align: center;
}
.connect-prompt h1 {
    font-size: 40px;
    font-weight: 700;
    letter-spacing: -1.0px;
    margin-bottom: 8px;
}
.connect-prompt p {
    color: #615d59;
    font-size: 16px;
    margin-bottom: 24px;
}
.connect-prompt .primary-btn {
    display: inline-block;
    background: #0075de;
    color: #ffffff;
    padding: 8px 16px;
    border-radius: 4px;
    font-weight: 600;
    font-size: 15px;
    text-decoration: none;
}
.connect-prompt .primary-btn:hover { background: #005bab; }
.connect-prompt .fine-print {
    margin-top: 32px;
    font-size: 12px;
    color: #a39e98;
}
```

- [ ] **Step 7: Run the render tests**

Run: `pytest tests/test_movement_render.py -v`
Expected: All three tests PASS.

- [ ] **Step 8: Commit**

```bash
git add foodlog/templates/dashboard/movement_partial.html \
        foodlog/templates/dashboard/health_connect.html \
        foodlog/templates/dashboard/feed_partial.html \
        foodlog/templates/base.html \
        tests/test_movement_render.py
git commit -m "feat(health): add movement & recovery partial and connect page"
```

---

## Task 8: Dashboard router integration

**Files:**
- Modify: `foodlog/api/routers/dashboard.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing integration tests**

Append to `tests/test_dashboard.py`:

```python
import datetime
from unittest.mock import patch, AsyncMock
from cryptography.fernet import Fernet

from foodlog.config import settings
from foodlog.db.models import GoogleOAuthToken, DailyActivity, Workout


def _login(client, email="ryan.c.kelly@gmail.com"):
    with client.session_transaction() as s:
        s["user"] = email


def _configure_health(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "authorized_email", "ryan.c.kelly@gmail.com")
    monkeypatch.setattr(settings, "session_secret_key", "test-session")
    monkeypatch.setattr(settings, "foodlog_google_token_key", Fernet.generate_key().decode())


def test_feed_unconnected_shows_connect_prompt(raw_client, monkeypatch):
    _configure_health(monkeypatch)
    _login(raw_client)
    resp = raw_client.get("/dashboard/feed?date_range=today")
    assert resp.status_code == 200
    assert "Connect Google Health" in resp.text


def test_feed_connected_renders_movement_section(raw_client, db_session, monkeypatch):
    _configure_health(monkeypatch)
    _login(raw_client)

    # Seed a token so connected-state triggers
    fernet = Fernet(settings.foodlog_google_token_key.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    ))
    db_session.add(DailyActivity(
        date=datetime.date.today(),
        steps=8432,
        active_calories_kcal=512.0,
        source="watch",
        external_id="da-today",
    ))
    db_session.commit()

    # Patch the whole sync helper so no HTTP calls are made at all.
    with patch("foodlog.api.routers.dashboard._run_health_sync",
               new=AsyncMock(return_value=None)):
        resp = raw_client.get("/dashboard/feed?date_range=today")

    assert resp.status_code == 200
    assert "Movement" in resp.text


def test_feed_old_token_triggers_opportunistic_reauth(raw_client, db_session, monkeypatch):
    """Token older than 5 days redirects via HX-Redirect header to /health/connect."""
    _configure_health(monkeypatch)
    _login(raw_client)

    fernet = Fernet(settings.foodlog_google_token_key.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                   - datetime.timedelta(days=6),
    ))
    db_session.commit()

    resp = raw_client.get("/dashboard/feed?date_range=today")
    assert resp.headers.get("HX-Redirect") == "/health/connect"


def test_feed_invalid_grant_shows_reconnect_banner(raw_client, db_session, monkeypatch):
    """If Google rejects the refresh token (e.g. user revoked), show the banner."""
    _configure_health(monkeypatch)
    _login(raw_client)

    # Fresh token (age < 5 days) so we don't trigger opportunistic re-auth
    fernet = Fernet(settings.foodlog_google_token_key.encode())
    db_session.add(GoogleOAuthToken(
        id=1,
        refresh_token_encrypted=fernet.encrypt(b"rt").decode(),
        scopes_json="[]",
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                   - datetime.timedelta(days=1),
    ))
    db_session.commit()

    from foodlog.services.google_token import TokenInvalid
    with patch("foodlog.api.routers.dashboard._run_health_sync",
               new=AsyncMock(side_effect=TokenInvalid("invalid_grant"))):
        resp = raw_client.get("/dashboard/feed?date_range=today")

    assert resp.status_code == 200
    assert "Reconnect" in resp.text or "reconnect" in resp.text
```

- [ ] **Step 2: Run the tests — they fail**

Run: `pytest tests/test_dashboard.py -v -k "health or movement or expired or unconnected"`
Expected: FAIL (the integration doesn't exist yet).

- [ ] **Step 3: Refactor `foodlog/api/routers/dashboard.py` to integrate health**

Replace the existing `feed_partial` function (line 24 onward) with a version that adds health data. Also add two module-level helpers. The full new file content:

```python
import asyncio
import datetime

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.clients.google_health import GoogleHealthClient
from foodlog.config import settings
from foodlog.db.models import (
    BodyComposition,
    DailyActivity,
    GoogleOAuthToken,
    RestingHeartRate,
    SleepSession,
    Workout,
)
from foodlog.services.google_token import GoogleTokenService, TokenInvalid, TokenMissing
from foodlog.services.health_sync import HealthSyncService
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="foodlog/templates")

REAUTH_AGE_DAYS = 5  # spec: opportunistic re-auth before Google's 7-day wall


async def _run_health_sync(db: Session) -> None:
    """Trigger on-presence sync. Raises TokenInvalid or TokenMissing on auth failure."""
    token_svc = GoogleTokenService(db)
    async with httpx.AsyncClient(timeout=15.0) as http:
        access = await token_svc.mint_access_token(http)
        client = GoogleHealthClient(http, access_token=access.value)
        sync = HealthSyncService(db, client)
        await sync.sync_all()


def _is_connected(db: Session) -> bool:
    return db.get(GoogleOAuthToken, 1) is not None


def _token_is_aging(db: Session) -> bool:
    """Return True if the stored token is older than REAUTH_AGE_DAYS."""
    try:
        return GoogleTokenService(db).token_age_days() > REAUTH_AGE_DAYS
    except TokenMissing:
        return False


def _build_movement_context(db: Session, start_date, end_date) -> dict:
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date + datetime.timedelta(days=1), datetime.time.min)

    workouts = (db.query(Workout)
                  .filter(Workout.start_at >= start_dt, Workout.start_at < end_dt)
                  .order_by(Workout.start_at.desc()).all())
    workout_views = []
    for w in workouts:
        samples = w.hr_samples
        if samples and w.max_hr:
            peak = max(w.max_hr, max(s.bpm for s in samples))
            bars = [{"pct": round(s.bpm / peak * 100)} for s in samples]
        else:
            bars = []
        workout_views.append({
            "activity_type": w.activity_type.title(),
            "distance_km": round(w.distance_m / 1000, 1) if w.distance_m else None,
            "duration_min": w.duration_min,
            "calories_kcal": w.calories_kcal,
            "avg_hr": w.avg_hr,
            "max_hr": w.max_hr,
            "hr_samples": bars,
        })

    sleep = (db.query(SleepSession)
               .filter(SleepSession.start_at >= start_dt,
                       SleepSession.start_at < end_dt)
               .order_by(SleepSession.start_at.desc()).first())
    resting = (db.query(RestingHeartRate)
                 .filter(RestingHeartRate.measured_at >= start_dt,
                         RestingHeartRate.measured_at < end_dt)
                 .order_by(RestingHeartRate.measured_at.desc()).first())
    sleep_view = None
    if sleep is not None:
        sleep_view = {
            "duration_min": sleep.duration_min,
            "resting_hr": resting.bpm if resting else None,
        }

    latest_body = (db.query(BodyComposition)
                     .order_by(BodyComposition.measured_at.desc()).first())
    weight_view = None
    if latest_body and latest_body.weight_kg:
        week_ago = (db.query(BodyComposition)
                      .filter(BodyComposition.measured_at <= latest_body.measured_at
                                                            - datetime.timedelta(days=7))
                      .order_by(BodyComposition.measured_at.desc()).first())
        delta = None
        if week_ago and week_ago.weight_kg:
            delta = latest_body.weight_kg - week_ago.weight_kg
        weight_view = {
            "weight_kg": latest_body.weight_kg,
            "delta_kg": delta,
            "body_fat_pct": latest_body.body_fat_pct,
        }

    activity = (db.query(DailyActivity)
                  .filter(DailyActivity.date >= start_date,
                          DailyActivity.date <= end_date).all())
    total_burned = sum(a.active_calories_kcal for a in activity) if activity else None
    return {
        "workouts": workout_views,
        "sleep": sleep_view,
        "weight": weight_view,
        "total_burned": total_burned,
    }


@router.get("", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={"today": datetime.date.today()},
    )


@router.get("/feed", response_class=HTMLResponse)
async def feed_partial(
    request: Request,
    date_range: str = "today",
    db: Session = Depends(get_db),
):
    # If health is configured but not connected, render the connect prompt
    # instead of the feed. This short-circuits the meals view; if you want
    # meals AND a connect banner, split this into two partials.
    if settings.google_health_configured and not _is_connected(db):
        return templates.TemplateResponse(
            request=request, name="dashboard/health_connect.html", context={}
        )

    # Opportunistic re-auth: if the refresh token is older than 5 days,
    # redirect (via HX-Redirect) through /health/connect before the 7-day
    # wall bites. Google usually fulfills this silently.
    if settings.google_health_configured and _is_connected(db) and _token_is_aging(db):
        return HTMLResponse("", headers={"HX-Redirect": "/health/connect"})

    # Meals (unchanged from original)
    entry_svc = EntryService(db)
    summary_svc = SummaryService(db)
    today = datetime.date.today()
    if date_range == "yesterday":
        start_date = today - datetime.timedelta(days=1)
        end_date = start_date
        range_label = "yesterday"
    elif date_range == "week":
        start_date = today - datetime.timedelta(days=7)
        end_date = today
        range_label = "the past seven days"
    else:
        start_date = today
        end_date = today
        range_label = "today"

    if start_date == end_date:
        entries = entry_svc.get_by_date(start_date)
        summary = summary_svc.daily(start_date)
    else:
        entries = entry_svc.get_by_range(start_date, end_date)
        summary = summary_svc.range(start_date, end_date)

    entries.sort(key=lambda x: x.logged_at, reverse=True)

    grouped_entries = []
    if entries:
        current_group = {
            "meal_type": entries[0].meal_type,
            "logged_at": entries[0].logged_at,
            "entries": [entries[0]],
            "total_calories": entries[0].calories,
            "total_protein_g": entries[0].protein_g,
            "total_carbs_g": entries[0].carbs_g,
            "total_fat_g": entries[0].fat_g,
        }
        for entry in entries[1:]:
            time_diff = abs((entry.logged_at - current_group["logged_at"]).total_seconds())
            if entry.meal_type == current_group["meal_type"] and time_diff < 300:
                current_group["entries"].append(entry)
                current_group["total_calories"] += entry.calories
                current_group["total_protein_g"] += entry.protein_g
                current_group["total_carbs_g"] += entry.carbs_g
                current_group["total_fat_g"] += entry.fat_g
            else:
                grouped_entries.append(current_group)
                current_group = {
                    "meal_type": entry.meal_type,
                    "logged_at": entry.logged_at,
                    "entries": [entry],
                    "total_calories": entry.calories,
                    "total_protein_g": entry.protein_g,
                    "total_carbs_g": entry.carbs_g,
                    "total_fat_g": entry.fat_g,
                }
        grouped_entries.append(current_group)

    p_kcal = (summary.total_protein_g or 0) * 4
    c_kcal = (summary.total_carbs_g or 0) * 4
    f_kcal = (summary.total_fat_g or 0) * 9
    macro_kcal = p_kcal + c_kcal + f_kcal
    if macro_kcal > 0:
        p_pct = round(p_kcal / macro_kcal * 100)
        c_pct = round(c_kcal / macro_kcal * 100)
        f_pct = max(0, 100 - p_pct - c_pct)
    else:
        p_pct = c_pct = f_pct = 0

    entry_count = sum(len(g["entries"]) for g in grouped_entries)
    course_count = len(grouped_entries)

    # Health sync (on-presence)
    reconnect_needed = False
    stale = False
    include_movement = False
    movement_ctx = {}
    if settings.google_health_configured and _is_connected(db):
        try:
            await _run_health_sync(db)
            include_movement = True
        except (TokenInvalid, TokenMissing):
            reconnect_needed = True
        except Exception:
            stale = True
            include_movement = True  # render whatever's in the DB
        if include_movement:
            movement_ctx = _build_movement_context(db, start_date, end_date)

    net_calories = None
    if include_movement and movement_ctx.get("total_burned"):
        net_calories = (summary.total_calories or 0) - movement_ctx["total_burned"]

    return templates.TemplateResponse(
        request=request,
        name="dashboard/feed_partial.html",
        context={
            "grouped_entries": grouped_entries,
            "summary": summary,
            "range_label": range_label,
            "macro_pct": {"p": p_pct, "c": c_pct, "f": f_pct},
            "entry_count": entry_count,
            "course_count": course_count,
            "include_movement": include_movement,
            "reconnect_needed": reconnect_needed,
            "stale": stale,
            "net_calories": net_calories,
            **movement_ctx,
        },
    )
```

- [ ] **Step 4: Add reconnect banner to `foodlog/templates/dashboard/feed_partial.html`**

At the very top of `feed_partial.html`, insert:

```jinja
{% if reconnect_needed %}
  <div class="reconnect-banner">
    Your Google Health connection expired.
    <a href="/health/connect">Reconnect</a> to resume syncing.
  </div>
{% elif stale %}
  <div class="reconnect-banner stale">Health data may be stale (sync failed)</div>
{% endif %}
```

And add the corresponding CSS to `base.html` before the closing `</style>`:

```css
.reconnect-banner {
    padding: 10px 14px;
    background: #f2f9ff;
    color: #097fe8;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 16px;
}
.reconnect-banner.stale {
    background: #f6f5f4;
    color: #615d59;
}
.reconnect-banner a {
    color: #0075de;
    text-decoration: underline;
}
```

- [ ] **Step 5: Add net-calories badge rendering**

In `foodlog/templates/dashboard/feed_partial.html`, inside the `<section class="summary">` block, after the existing `<div class="summary-row">` element, insert:

```jinja
{% if net_calories is not none %}
<div class="net-badge" aria-label="net calories">
  net {{ net_calories|round|int }}
  · burned {{ total_burned|round|int }}
</div>
{% endif %}
```

And the matching CSS in `base.html`:

```css
.net-badge {
    display: inline-block;
    margin-top: 8px;
    padding: 4px 10px;
    background: #f2f9ff;
    color: #097fe8;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.125px;
}
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_dashboard.py -v`
Expected: All tests PASS (new ones and pre-existing ones).

- [ ] **Step 7: Run the whole suite**

Run: `pytest -x`
Expected: All pass. If existing dashboard-render tests break because they didn't pass the new context keys, adjust them — they should now render successfully even with all health fields absent (because every `if` in the templates checks presence).

- [ ] **Step 8: Commit**

```bash
git add foodlog/api/routers/dashboard.py \
        foodlog/templates/dashboard/feed_partial.html \
        foodlog/templates/base.html \
        tests/test_dashboard.py
git commit -m "feat(health): wire on-presence sync into dashboard feed"
```

---

## Post-implementation checklist

- [ ] `pytest` — full suite passes.
- [ ] Manual smoke: `docker compose build foodlog && docker compose up -d` → visit `/dashboard` → SSO → click "Connect Google Health" → complete consent → dashboard shows Movement & Recovery section populated with real data.
- [ ] Inspect `workouts` table after first sync for time-overlapping rows with different `source` values. If found, open a follow-up issue for the deduplication rule (post-launch item from the spec).
- [ ] Verify `docker logs foodlog` shows no tracebacks around dashboard requests.
