# Food Logger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MCP-based food logging system with a FastAPI backend, FatSecret + USDA nutrition lookups, and local SQLite diary.

**Architecture:** FastAPI service handles all business logic and data access. MCP server is a thin HTTP client exposing FastAPI endpoints as Claude tools. SQLite is the single source of truth for diary entries. FatSecret and USDA are read-only nutrition databases.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, httpx, MCP Python SDK (`mcp[cli]`), SQLite, pytest

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Project metadata, dependencies, entry points |
| `.env.example` | Template for environment variables |
| `foodlog/config.py` | Pydantic Settings loading from env vars |
| `foodlog/db/database.py` | SQLite engine, session factory, table creation |
| `foodlog/db/models.py` | SQLAlchemy `FoodEntry` model |
| `foodlog/models/schemas.py` | Pydantic request/response schemas |
| `foodlog/services/logging.py` | CRUD operations on food_entries |
| `foodlog/services/nutrition.py` | Daily/range summary aggregation |
| `foodlog/services/search.py` | Search orchestration with FatSecret/USDA fallback |
| `foodlog/clients/usda.py` | USDA FoodData Central API client |
| `foodlog/clients/fatsecret.py` | FatSecret API client with OAuth 1.0 signing |
| `foodlog/api/dependencies.py` | FastAPI dependency injection (DB session, clients) |
| `foodlog/api/routers/entries.py` | Diary CRUD endpoints |
| `foodlog/api/routers/summary.py` | Summary endpoints |
| `foodlog/api/routers/foods.py` | Food search endpoints |
| `foodlog/api/app.py` | FastAPI app, lifespan, health endpoint, router mounting |
| `mcp_server/server.py` | MCP tools wrapping FastAPI HTTP calls |
| `.mcp.json` | MCP server registration for Claude Code |
| `tests/conftest.py` | Shared fixtures (test DB, test client, mock clients) |
| `tests/test_db.py` | Database model tests |
| `tests/test_services.py` | Service layer tests |
| `tests/test_api.py` | FastAPI endpoint tests |
| `tests/test_clients.py` | API client tests (mocked HTTP) |
| `tests/test_mcp.py` | MCP tool tests |

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `foodlog/__init__.py`
- Create: `foodlog/config.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "foodlog"
version = "0.1.0"
description = "Natural language food logger with MCP interface"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy>=2.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "httpx>=0.27.0",
    "mcp[cli]>=1.2.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-httpx>=0.30.0",
    "respx>=0.22.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create .env.example**

```
FATSECRET_CONSUMER_KEY=
FATSECRET_CONSUMER_SECRET=
USDA_API_KEY=
FOODLOG_DB_PATH=~/.foodlog/foodlog.db
FOODLOG_HOST=127.0.0.1
FOODLOG_PORT=8042
```

- [ ] **Step 3: Create foodlog/config.py**

```python
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    fatsecret_consumer_key: str = ""
    fatsecret_consumer_secret: str = ""
    usda_api_key: str = ""
    foodlog_db_path: str = str(Path.home() / ".foodlog" / "foodlog.db")
    foodlog_host: str = "127.0.0.1"
    foodlog_port: int = 8042

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.foodlog_db_path}"

    @property
    def fatsecret_configured(self) -> bool:
        return bool(self.fatsecret_consumer_key and self.fatsecret_consumer_secret)

    @property
    def usda_configured(self) -> bool:
        return bool(self.usda_api_key)


settings = Settings()
```

- [ ] **Step 4: Create empty __init__.py files**

Create `foodlog/__init__.py` and `tests/__init__.py` as empty files.

- [ ] **Step 5: Create venv and install dependencies**

Run:
```bash
cd /home/ryan/foodlog
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: all packages install successfully.

- [ ] **Step 6: Verify config loads**

Run:
```bash
cd /home/ryan/foodlog
source .venv/bin/activate
python -c "from foodlog.config import settings; print(settings.foodlog_port)"
```

Expected: `8042`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .env.example foodlog/__init__.py foodlog/config.py tests/__init__.py
git commit -m "feat: project scaffolding with config and dependencies"
```

---

### Task 2: Database Layer

**Files:**
- Create: `foodlog/db/__init__.py`
- Create: `foodlog/db/database.py`
- Create: `foodlog/db/models.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py`:

```python
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from foodlog.db.models import Base, FoodEntry


def test_create_food_entry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        entry = FoodEntry(
            meal_type="lunch",
            food_name="Chicken Breast",
            quantity=1.0,
            unit="serving",
            weight_g=150.0,
            calories=247.5,
            protein_g=46.5,
            carbs_g=0.0,
            fat_g=5.4,
            source="fatsecret",
            source_id="33691",
            raw_input="grilled chicken breast",
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)

        assert entry.id is not None
        assert entry.food_name == "Chicken Breast"
        assert entry.calories == 247.5
        assert entry.logged_at is not None
        assert entry.created_at is not None


def test_nullable_fields():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        entry = FoodEntry(
            meal_type="snack",
            food_name="Apple",
            quantity=1.0,
            unit="medium",
            calories=95.0,
            protein_g=0.5,
            carbs_g=25.0,
            fat_g=0.3,
            source="usda",
            source_id="171688",
            raw_input="an apple",
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)

        assert entry.weight_g is None
        assert entry.fiber_g is None
        assert entry.sugar_g is None
        assert entry.sodium_mg is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_db.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'foodlog.db'`

- [ ] **Step 3: Create database.py**

Create `foodlog/db/__init__.py` (empty) and `foodlog/db/database.py`:

```python
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from foodlog.config import settings


def get_engine(db_url: str | None = None):
    url = db_url or settings.database_url
    db_path = url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, echo=False)


def get_session_factory(engine=None):
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine)
```

- [ ] **Step 4: Create models.py**

Create `foodlog/db/models.py`:

```python
import datetime

from sqlalchemy import Float, Integer, String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class FoodEntry(Base):
    __tablename__ = "food_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meal_type: Mapped[str] = mapped_column(String(20))
    food_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(50))
    weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    carbs_g: Mapped[float] = mapped_column(Float)
    fat_g: Mapped[float] = mapped_column(Float)
    fiber_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sugar_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sodium_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_input: Mapped[str] = mapped_column(Text)
    logged_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_db.py -v`

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add foodlog/db/ tests/test_db.py
git commit -m "feat: database layer with FoodEntry model"
```

---

### Task 3: Pydantic Schemas

**Files:**
- Create: `foodlog/models/__init__.py`
- Create: `foodlog/models/schemas.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py` (or create a new test — we'll add schema validation tests at the end of the file):

Create `tests/test_schemas.py`:

```python
import datetime

import pytest
from pydantic import ValidationError

from foodlog.models.schemas import (
    FoodEntryCreate,
    FoodEntryResponse,
    FoodSearchResult,
    DailySummary,
    MealSummary,
)


def test_food_entry_create_valid():
    entry = FoodEntryCreate(
        meal_type="lunch",
        food_name="Chicken Breast",
        quantity=1.0,
        unit="serving",
        calories=247.5,
        protein_g=46.5,
        carbs_g=0.0,
        fat_g=5.4,
        source="fatsecret",
        source_id="33691",
        raw_input="grilled chicken breast",
    )
    assert entry.meal_type == "lunch"
    assert entry.weight_g is None


def test_food_entry_create_invalid_meal_type():
    with pytest.raises(ValidationError):
        FoodEntryCreate(
            meal_type="brunch",
            food_name="Toast",
            quantity=1.0,
            unit="slice",
            calories=80.0,
            protein_g=3.0,
            carbs_g=14.0,
            fat_g=1.0,
            source="usda",
            raw_input="toast",
        )


def test_food_search_result():
    result = FoodSearchResult(
        food_id="33691",
        food_name="Chicken Breast",
        source="fatsecret",
        calories=165.0,
        protein_g=31.0,
        carbs_g=0.0,
        fat_g=3.6,
        serving_description="Per 100g",
    )
    assert result.source == "fatsecret"


def test_daily_summary():
    meal = MealSummary(
        meal_type="lunch",
        calories=500.0,
        protein_g=40.0,
        carbs_g=50.0,
        fat_g=15.0,
        entry_count=2,
    )
    summary = DailySummary(
        date=datetime.date(2026, 4, 15),
        meals=[meal],
        total_calories=500.0,
        total_protein_g=40.0,
        total_carbs_g=50.0,
        total_fat_g=15.0,
    )
    assert summary.total_calories == 500.0
    assert len(summary.meals) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_schemas.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'foodlog.models'`

- [ ] **Step 3: Create schemas.py**

Create `foodlog/models/__init__.py` (empty) and `foodlog/models/schemas.py`:

```python
import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MealType(str, Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"


class FoodEntryCreate(BaseModel):
    meal_type: MealType
    food_name: str
    quantity: float = Field(gt=0)
    unit: str
    weight_g: float | None = None
    calories: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    fiber_g: float | None = None
    sugar_g: float | None = None
    sodium_mg: float | None = None
    source: str
    source_id: str | None = None
    raw_input: str
    logged_at: datetime.datetime | None = None


class FoodEntryUpdate(BaseModel):
    meal_type: MealType | None = None
    food_name: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    weight_g: float | None = None
    calories: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbs_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    source: str | None = None
    source_id: str | None = None


class FoodEntryResponse(BaseModel):
    id: int
    meal_type: str
    food_name: str
    quantity: float
    unit: str
    weight_g: float | None
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None
    sugar_g: float | None
    sodium_mg: float | None
    source: str
    source_id: str | None
    raw_input: str
    logged_at: datetime.datetime
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class FoodSearchResult(BaseModel):
    food_id: str
    food_name: str
    source: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    serving_description: str
    fiber_g: float | None = None
    sugar_g: float | None = None
    sodium_mg: float | None = None


class MealSummary(BaseModel):
    meal_type: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    entry_count: int


class DailySummary(BaseModel):
    date: datetime.date
    meals: list[MealSummary]
    total_calories: float
    total_protein_g: float
    total_carbs_g: float
    total_fat_g: float


class RangeSummary(BaseModel):
    start_date: datetime.date
    end_date: datetime.date
    days: int
    total_calories: float
    total_protein_g: float
    total_carbs_g: float
    total_fat_g: float
    avg_daily_calories: float
    avg_daily_protein_g: float
    avg_daily_carbs_g: float
    avg_daily_fat_g: float
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_schemas.py -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add foodlog/models/ tests/test_schemas.py
git commit -m "feat: Pydantic schemas for entries, search results, summaries"
```

---

### Task 4: Entry Service (CRUD)

**Files:**
- Create: `foodlog/services/__init__.py`
- Create: `foodlog/services/logging.py`
- Create: `tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services.py`:

```python
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from foodlog.db.models import Base, FoodEntry
from foodlog.models.schemas import FoodEntryCreate, FoodEntryUpdate, MealType
from foodlog.services.logging import EntryService


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def sample_entry() -> FoodEntryCreate:
    return FoodEntryCreate(
        meal_type=MealType.lunch,
        food_name="Chicken Breast",
        quantity=1.0,
        unit="serving",
        weight_g=150.0,
        calories=247.5,
        protein_g=46.5,
        carbs_g=0.0,
        fat_g=5.4,
        source="fatsecret",
        source_id="33691",
        raw_input="grilled chicken breast",
    )


def test_create_entry():
    session = make_session()
    svc = EntryService(session)
    entry = svc.create(sample_entry())
    assert entry.id is not None
    assert entry.food_name == "Chicken Breast"
    assert entry.calories == 247.5


def test_create_multiple_entries():
    session = make_session()
    svc = EntryService(session)
    entries_data = [
        sample_entry(),
        FoodEntryCreate(
            meal_type=MealType.lunch,
            food_name="White Rice",
            quantity=1.5,
            unit="cup",
            weight_g=280.0,
            calories=340.0,
            protein_g=6.0,
            carbs_g=74.0,
            fat_g=1.0,
            source="fatsecret",
            source_id="12345",
            raw_input="cup and a half of rice",
        ),
    ]
    results = svc.create_many(entries_data)
    assert len(results) == 2
    assert results[0].food_name == "Chicken Breast"
    assert results[1].food_name == "White Rice"


def test_get_entries_by_date():
    session = make_session()
    svc = EntryService(session)
    svc.create(sample_entry())
    entries = svc.get_by_date(datetime.date.today())
    assert len(entries) == 1
    assert entries[0].food_name == "Chicken Breast"


def test_get_entries_by_date_and_meal():
    session = make_session()
    svc = EntryService(session)
    svc.create(sample_entry())
    lunch = svc.get_by_date(datetime.date.today(), meal_type="lunch")
    dinner = svc.get_by_date(datetime.date.today(), meal_type="dinner")
    assert len(lunch) == 1
    assert len(dinner) == 0


def test_update_entry():
    session = make_session()
    svc = EntryService(session)
    entry = svc.create(sample_entry())
    updated = svc.update(entry.id, FoodEntryUpdate(quantity=2.0, calories=495.0))
    assert updated.quantity == 2.0
    assert updated.calories == 495.0
    assert updated.food_name == "Chicken Breast"


def test_delete_entry():
    session = make_session()
    svc = EntryService(session)
    entry = svc.create(sample_entry())
    assert svc.delete(entry.id) is True
    assert svc.get_by_date(datetime.date.today()) == []


def test_delete_nonexistent_entry():
    session = make_session()
    svc = EntryService(session)
    assert svc.delete(999) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_services.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'foodlog.services'`

- [ ] **Step 3: Implement EntryService**

Create `foodlog/services/__init__.py` (empty) and `foodlog/services/logging.py`:

```python
import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from foodlog.db.models import FoodEntry
from foodlog.models.schemas import FoodEntryCreate, FoodEntryUpdate


class EntryService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, data: FoodEntryCreate) -> FoodEntry:
        entry = FoodEntry(
            meal_type=data.meal_type.value,
            food_name=data.food_name,
            quantity=data.quantity,
            unit=data.unit,
            weight_g=data.weight_g,
            calories=data.calories,
            protein_g=data.protein_g,
            carbs_g=data.carbs_g,
            fat_g=data.fat_g,
            fiber_g=data.fiber_g,
            sugar_g=data.sugar_g,
            sodium_mg=data.sodium_mg,
            source=data.source,
            source_id=data.source_id,
            raw_input=data.raw_input,
            logged_at=data.logged_at or datetime.datetime.now(),
        )
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def create_many(self, items: list[FoodEntryCreate]) -> list[FoodEntry]:
        entries = []
        for data in items:
            entry = FoodEntry(
                meal_type=data.meal_type.value,
                food_name=data.food_name,
                quantity=data.quantity,
                unit=data.unit,
                weight_g=data.weight_g,
                calories=data.calories,
                protein_g=data.protein_g,
                carbs_g=data.carbs_g,
                fat_g=data.fat_g,
                fiber_g=data.fiber_g,
                sugar_g=data.sugar_g,
                sodium_mg=data.sodium_mg,
                source=data.source,
                source_id=data.source_id,
                raw_input=data.raw_input,
                logged_at=data.logged_at or datetime.datetime.now(),
            )
            self.session.add(entry)
            entries.append(entry)
        self.session.commit()
        for e in entries:
            self.session.refresh(e)
        return entries

    def get_by_date(
        self, date: datetime.date, meal_type: str | None = None
    ) -> list[FoodEntry]:
        query = self.session.query(FoodEntry).filter(
            func.date(FoodEntry.logged_at) == date
        )
        if meal_type:
            query = query.filter(FoodEntry.meal_type == meal_type)
        return query.order_by(FoodEntry.logged_at).all()

    def update(self, entry_id: int, data: FoodEntryUpdate) -> FoodEntry | None:
        entry = self.session.get(FoodEntry, entry_id)
        if not entry:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            if hasattr(value, "value"):
                value = value.value
            setattr(entry, field, value)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def delete(self, entry_id: int) -> bool:
        entry = self.session.get(FoodEntry, entry_id)
        if not entry:
            return False
        self.session.delete(entry)
        self.session.commit()
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_services.py -v`

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/ tests/test_services.py
git commit -m "feat: entry service with CRUD operations"
```

---

### Task 5: Summary Service

**Files:**
- Create: `foodlog/services/nutrition.py`
- Modify: `tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_services.py`:

```python
from foodlog.services.nutrition import SummaryService


def test_daily_summary():
    session = make_session()
    entry_svc = EntryService(session)
    entry_svc.create(sample_entry())
    entry_svc.create(
        FoodEntryCreate(
            meal_type=MealType.lunch,
            food_name="White Rice",
            quantity=1.5,
            unit="cup",
            calories=340.0,
            protein_g=6.0,
            carbs_g=74.0,
            fat_g=1.0,
            source="fatsecret",
            raw_input="rice",
        )
    )

    summary_svc = SummaryService(session)
    summary = summary_svc.daily(datetime.date.today())
    assert summary.total_calories == 587.5
    assert summary.total_protein_g == 52.5
    assert len(summary.meals) == 1
    assert summary.meals[0].meal_type == "lunch"
    assert summary.meals[0].entry_count == 2


def test_daily_summary_multiple_meals():
    session = make_session()
    entry_svc = EntryService(session)
    entry_svc.create(sample_entry())
    entry_svc.create(
        FoodEntryCreate(
            meal_type=MealType.snack,
            food_name="Apple",
            quantity=1.0,
            unit="medium",
            calories=95.0,
            protein_g=0.5,
            carbs_g=25.0,
            fat_g=0.3,
            source="usda",
            raw_input="apple",
        )
    )

    summary_svc = SummaryService(session)
    summary = summary_svc.daily(datetime.date.today())
    assert summary.total_calories == 342.5
    assert len(summary.meals) == 2


def test_daily_summary_empty():
    session = make_session()
    summary_svc = SummaryService(session)
    summary = summary_svc.daily(datetime.date.today())
    assert summary.total_calories == 0.0
    assert summary.meals == []


def test_range_summary():
    session = make_session()
    entry_svc = EntryService(session)
    entry_svc.create(sample_entry())

    summary_svc = SummaryService(session)
    today = datetime.date.today()
    result = summary_svc.range(today, today)
    assert result.total_calories == 247.5
    assert result.days == 1
    assert result.avg_daily_calories == 247.5
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_services.py::test_daily_summary -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'foodlog.services.nutrition'`

- [ ] **Step 3: Implement SummaryService**

Create `foodlog/services/nutrition.py`:

```python
import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from foodlog.db.models import FoodEntry
from foodlog.models.schemas import DailySummary, MealSummary, RangeSummary


class SummaryService:
    def __init__(self, session: Session):
        self.session = session

    def daily(self, date: datetime.date) -> DailySummary:
        rows = (
            self.session.query(
                FoodEntry.meal_type,
                func.sum(FoodEntry.calories).label("calories"),
                func.sum(FoodEntry.protein_g).label("protein_g"),
                func.sum(FoodEntry.carbs_g).label("carbs_g"),
                func.sum(FoodEntry.fat_g).label("fat_g"),
                func.count(FoodEntry.id).label("entry_count"),
            )
            .filter(func.date(FoodEntry.logged_at) == date)
            .group_by(FoodEntry.meal_type)
            .all()
        )

        meals = [
            MealSummary(
                meal_type=row.meal_type,
                calories=row.calories,
                protein_g=row.protein_g,
                carbs_g=row.carbs_g,
                fat_g=row.fat_g,
                entry_count=row.entry_count,
            )
            for row in rows
        ]

        return DailySummary(
            date=date,
            meals=meals,
            total_calories=sum(m.calories for m in meals),
            total_protein_g=sum(m.protein_g for m in meals),
            total_carbs_g=sum(m.carbs_g for m in meals),
            total_fat_g=sum(m.fat_g for m in meals),
        )

    def range(self, start: datetime.date, end: datetime.date) -> RangeSummary:
        row = (
            self.session.query(
                func.sum(FoodEntry.calories).label("calories"),
                func.sum(FoodEntry.protein_g).label("protein_g"),
                func.sum(FoodEntry.carbs_g).label("carbs_g"),
                func.sum(FoodEntry.fat_g).label("fat_g"),
            )
            .filter(func.date(FoodEntry.logged_at).between(start, end))
            .one()
        )

        days = (end - start).days + 1
        total_cal = row.calories or 0.0
        total_pro = row.protein_g or 0.0
        total_carb = row.carbs_g or 0.0
        total_fat = row.fat_g or 0.0

        return RangeSummary(
            start_date=start,
            end_date=end,
            days=days,
            total_calories=total_cal,
            total_protein_g=total_pro,
            total_carbs_g=total_carb,
            total_fat_g=total_fat,
            avg_daily_calories=total_cal / days,
            avg_daily_protein_g=total_pro / days,
            avg_daily_carbs_g=total_carb / days,
            avg_daily_fat_g=total_fat / days,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_services.py -v`

Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/nutrition.py tests/test_services.py
git commit -m "feat: summary service with daily and range aggregation"
```

---

### Task 6: USDA Client

**Files:**
- Create: `foodlog/clients/__init__.py`
- Create: `foodlog/clients/usda.py`
- Create: `tests/test_clients.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_clients.py`:

```python
import httpx
import pytest
import respx

from foodlog.clients.usda import USDAClient
from foodlog.models.schemas import FoodSearchResult

USDA_BASE = "https://api.nal.usda.gov/fdc/v1"


@respx.mock
@pytest.mark.asyncio
async def test_usda_search():
    respx.get(f"{USDA_BASE}/foods/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "foods": [
                    {
                        "fdcId": 171688,
                        "description": "Apple, raw",
                        "foodNutrients": [
                            {"nutrientName": "Energy", "value": 52.0, "unitName": "KCAL"},
                            {"nutrientName": "Protein", "value": 0.26, "unitName": "G"},
                            {
                                "nutrientName": "Carbohydrate, by difference",
                                "value": 13.81,
                                "unitName": "G",
                            },
                            {
                                "nutrientName": "Total lipid (fat)",
                                "value": 0.17,
                                "unitName": "G",
                            },
                        ],
                    }
                ]
            },
        )
    )

    async with httpx.AsyncClient() as http:
        client = USDAClient(api_key="test-key", http_client=http)
        results = await client.search("apple")

    assert len(results) == 1
    assert results[0].food_name == "Apple, raw"
    assert results[0].source == "usda"
    assert results[0].food_id == "171688"
    assert results[0].calories == 52.0
    assert results[0].protein_g == 0.26


@respx.mock
@pytest.mark.asyncio
async def test_usda_search_empty():
    respx.get(f"{USDA_BASE}/foods/search").mock(
        return_value=httpx.Response(200, json={"foods": []})
    )

    async with httpx.AsyncClient() as http:
        client = USDAClient(api_key="test-key", http_client=http)
        results = await client.search("xyznonexistent")

    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_clients.py::test_usda_search -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'foodlog.clients'`

- [ ] **Step 3: Implement USDAClient**

Create `foodlog/clients/__init__.py` (empty) and `foodlog/clients/usda.py`:

```python
import httpx

from foodlog.models.schemas import FoodSearchResult

USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

NUTRIENT_MAP = {
    "Energy": "calories",
    "Protein": "protein_g",
    "Carbohydrate, by difference": "carbs_g",
    "Total lipid (fat)": "fat_g",
    "Fiber, total dietary": "fiber_g",
    "Sugars, Total": "sugar_g",
    "Sodium, Na": "sodium_mg",
}


class USDAClient:
    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        self.api_key = api_key
        self.http = http_client

    async def search(self, query: str, page_size: int = 10) -> list[FoodSearchResult]:
        resp = await self.http.get(
            f"{USDA_BASE_URL}/foods/search",
            params={
                "query": query,
                "api_key": self.api_key,
                "pageSize": page_size,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for food in data.get("foods", []):
            nutrients = self._extract_nutrients(food.get("foodNutrients", []))
            if nutrients.get("calories") is None:
                continue
            results.append(
                FoodSearchResult(
                    food_id=str(food["fdcId"]),
                    food_name=food["description"],
                    source="usda",
                    calories=nutrients.get("calories", 0),
                    protein_g=nutrients.get("protein_g", 0),
                    carbs_g=nutrients.get("carbs_g", 0),
                    fat_g=nutrients.get("fat_g", 0),
                    fiber_g=nutrients.get("fiber_g"),
                    sugar_g=nutrients.get("sugar_g"),
                    sodium_mg=nutrients.get("sodium_mg"),
                    serving_description=f"Per 100g",
                )
            )
        return results

    def _extract_nutrients(self, nutrients: list[dict]) -> dict:
        result = {}
        for n in nutrients:
            key = NUTRIENT_MAP.get(n.get("nutrientName"))
            if key:
                result[key] = n.get("value", 0)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_clients.py -v`

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add foodlog/clients/ tests/test_clients.py
git commit -m "feat: USDA FoodData Central API client"
```

---

### Task 7: FatSecret Client

**Files:**
- Create: `foodlog/clients/fatsecret.py`
- Modify: `tests/test_clients.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_clients.py`:

```python
from foodlog.clients.fatsecret import FatSecretClient


@respx.mock
@pytest.mark.asyncio
async def test_fatsecret_search():
    respx.get("https://platform.fatsecret.com/rest/server.api").mock(
        return_value=httpx.Response(
            200,
            json={
                "foods": {
                    "food": [
                        {
                            "food_id": "33691",
                            "food_name": "Chicken Breast",
                            "food_type": "Generic",
                            "food_description": "Per 100g - Calories: 165kcal | Fat: 3.57g | Carbs: 0.00g | Protein: 31.02g",
                        }
                    ]
                }
            },
        )
    )

    async with httpx.AsyncClient() as http:
        client = FatSecretClient(
            consumer_key="test-key",
            consumer_secret="test-secret",
            http_client=http,
        )
        results = await client.search("chicken breast")

    assert len(results) == 1
    assert results[0].food_name == "Chicken Breast"
    assert results[0].source == "fatsecret"
    assert results[0].food_id == "33691"
    assert results[0].calories == 165.0
    assert results[0].protein_g == 31.02


@respx.mock
@pytest.mark.asyncio
async def test_fatsecret_search_empty():
    respx.get("https://platform.fatsecret.com/rest/server.api").mock(
        return_value=httpx.Response(200, json={"foods": {"total_results": "0"}})
    )

    async with httpx.AsyncClient() as http:
        client = FatSecretClient(
            consumer_key="test-key",
            consumer_secret="test-secret",
            http_client=http,
        )
        results = await client.search("xyznonexistent")

    assert results == []
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_clients.py::test_fatsecret_search -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'foodlog.clients.fatsecret'`

- [ ] **Step 3: Implement FatSecretClient**

Create `foodlog/clients/fatsecret.py`:

```python
import base64
import hashlib
import hmac
import re
import time
import urllib.parse
import uuid

import httpx

from foodlog.models.schemas import FoodSearchResult

FATSECRET_API_URL = "https://platform.fatsecret.com/rest/server.api"


def _oauth_sign(consumer_key: str, consumer_secret: str, params: dict) -> dict:
    """Add OAuth 1.0 two-legged signature to params."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }
    all_params = {**params, **oauth_params}

    sorted_encoded = "&".join(
        f"{urllib.parse.quote(k, safe='')}"
        f"={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_string = "&".join(
        urllib.parse.quote(s, safe="")
        for s in ["GET", FATSECRET_API_URL, sorted_encoded]
    )

    signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&"
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()

    all_params["oauth_signature"] = sig
    return all_params


def _parse_description(desc: str) -> dict:
    """Parse FatSecret food_description string into numeric values.

    Example: "Per 100g - Calories: 165kcal | Fat: 3.57g | Carbs: 0.00g | Protein: 31.02g"
    """
    result = {}
    cal_match = re.search(r"Calories:\s*([\d.]+)", desc)
    fat_match = re.search(r"Fat:\s*([\d.]+)", desc)
    carb_match = re.search(r"Carbs:\s*([\d.]+)", desc)
    protein_match = re.search(r"Protein:\s*([\d.]+)", desc)
    serving_match = re.search(r"^(.*?)\s*-\s*Calories", desc)

    result["calories"] = float(cal_match.group(1)) if cal_match else 0.0
    result["fat_g"] = float(fat_match.group(1)) if fat_match else 0.0
    result["carbs_g"] = float(carb_match.group(1)) if carb_match else 0.0
    result["protein_g"] = float(protein_match.group(1)) if protein_match else 0.0
    result["serving_description"] = (
        serving_match.group(1).strip() if serving_match else "Per serving"
    )
    return result


class FatSecretClient:
    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        http_client: httpx.AsyncClient,
    ):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.http = http_client

    async def search(
        self, query: str, max_results: int = 10
    ) -> list[FoodSearchResult]:
        params = _oauth_sign(
            self.consumer_key,
            self.consumer_secret,
            {
                "method": "foods.search",
                "search_expression": query,
                "format": "json",
                "max_results": str(max_results),
            },
        )
        resp = await self.http.get(FATSECRET_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        foods_data = data.get("foods", {})
        food_list = foods_data.get("food", [])
        if not isinstance(food_list, list):
            food_list = [food_list] if food_list else []

        results = []
        for food in food_list:
            desc = food.get("food_description", "")
            parsed = _parse_description(desc)
            results.append(
                FoodSearchResult(
                    food_id=food["food_id"],
                    food_name=food["food_name"],
                    source="fatsecret",
                    calories=parsed["calories"],
                    protein_g=parsed["protein_g"],
                    carbs_g=parsed["carbs_g"],
                    fat_g=parsed["fat_g"],
                    serving_description=parsed["serving_description"],
                )
            )
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_clients.py -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add foodlog/clients/fatsecret.py tests/test_clients.py
git commit -m "feat: FatSecret API client with OAuth 1.0 two-legged signing"
```

---

### Task 8: Search Service (Orchestration + Fallback)

**Files:**
- Create: `foodlog/services/search.py`
- Modify: `tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_services.py`:

```python
import pytest

from foodlog.models.schemas import FoodSearchResult
from foodlog.services.search import SearchService


class FakeFatSecretClient:
    def __init__(self, results: list[FoodSearchResult]):
        self._results = results

    async def search(self, query: str, max_results: int = 10):
        return self._results


class FakeUSDAClient:
    def __init__(self, results: list[FoodSearchResult]):
        self._results = results

    async def search(self, query: str, page_size: int = 10):
        return self._results


def make_result(name, source, food_id="1"):
    return FoodSearchResult(
        food_id=food_id,
        food_name=name,
        source=source,
        calories=100.0,
        protein_g=10.0,
        carbs_g=20.0,
        fat_g=5.0,
        serving_description="Per 100g",
    )


@pytest.mark.asyncio
async def test_search_fatsecret_primary():
    fs = FakeFatSecretClient([make_result("Chicken", "fatsecret")])
    usda = FakeUSDAClient([make_result("Chicken", "usda")])
    svc = SearchService(fatsecret=fs, usda=usda)
    results = await svc.search("chicken")
    assert len(results) == 1
    assert results[0].source == "fatsecret"


@pytest.mark.asyncio
async def test_search_fallback_to_usda():
    fs = FakeFatSecretClient([])
    usda = FakeUSDAClient([make_result("Chicken", "usda")])
    svc = SearchService(fatsecret=fs, usda=usda)
    results = await svc.search("chicken")
    assert len(results) == 1
    assert results[0].source == "usda"


@pytest.mark.asyncio
async def test_search_no_fatsecret():
    usda = FakeUSDAClient([make_result("Chicken", "usda")])
    svc = SearchService(fatsecret=None, usda=usda)
    results = await svc.search("chicken")
    assert len(results) == 1
    assert results[0].source == "usda"


@pytest.mark.asyncio
async def test_search_no_clients():
    svc = SearchService(fatsecret=None, usda=None)
    with pytest.raises(RuntimeError, match="No food database APIs configured"):
        await svc.search("chicken")
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_services.py::test_search_fatsecret_primary -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'foodlog.services.search'`

- [ ] **Step 3: Implement SearchService**

Create `foodlog/services/search.py`:

```python
from foodlog.clients.fatsecret import FatSecretClient
from foodlog.clients.usda import USDAClient
from foodlog.models.schemas import FoodSearchResult


class SearchService:
    def __init__(
        self,
        fatsecret: FatSecretClient | None = None,
        usda: USDAClient | None = None,
    ):
        self.fatsecret = fatsecret
        self.usda = usda

    async def search(self, query: str) -> list[FoodSearchResult]:
        if self.fatsecret:
            results = await self.fatsecret.search(query)
            if results:
                return results

        if self.usda:
            results = await self.usda.search(query)
            if results:
                return results

        if not self.fatsecret and not self.usda:
            raise RuntimeError(
                "No food database APIs configured. "
                "Set FATSECRET_CONSUMER_KEY/SECRET or USDA_API_KEY in .env"
            )

        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_services.py -v`

Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/search.py tests/test_services.py
git commit -m "feat: search service with FatSecret primary, USDA fallback"
```

---

### Task 9: FastAPI App + Dependencies + Health Endpoint

**Files:**
- Create: `foodlog/api/__init__.py`
- Create: `foodlog/api/dependencies.py`
- Create: `foodlog/api/app.py`
- Create: `foodlog/api/routers/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from foodlog.api.app import create_app
from foodlog.api.dependencies import get_db
from foodlog.db.models import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)
```

Create `tests/test_api.py`:

```python
def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "fatsecret" in data
    assert "usda" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_api.py::test_health -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'foodlog.api'`

- [ ] **Step 3: Create dependencies.py**

Create `foodlog/api/__init__.py` (empty), `foodlog/api/routers/__init__.py` (empty), and `foodlog/api/dependencies.py`:

```python
from collections.abc import Generator

import httpx
from sqlalchemy.orm import Session

from foodlog.clients.fatsecret import FatSecretClient
from foodlog.clients.usda import USDAClient
from foodlog.config import settings
from foodlog.db.database import get_session_factory

_session_factory = None
_http_client: httpx.AsyncClient | None = None


def get_db() -> Generator[Session, None, None]:
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory()
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


def get_fatsecret_client() -> FatSecretClient | None:
    if not settings.fatsecret_configured:
        return None
    return FatSecretClient(
        consumer_key=settings.fatsecret_consumer_key,
        consumer_secret=settings.fatsecret_consumer_secret,
        http_client=get_http_client(),
    )


def get_usda_client() -> USDAClient | None:
    if not settings.usda_configured:
        return None
    return USDAClient(
        api_key=settings.usda_api_key,
        http_client=get_http_client(),
    )


async def cleanup_http_client():
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
```

- [ ] **Step 4: Create app.py**

Create `foodlog/api/app.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from foodlog.api.dependencies import cleanup_http_client
from foodlog.config import settings
from foodlog.db.database import get_engine
from foodlog.db.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    Base.metadata.create_all(engine)
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

    return app
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_api.py -v`

Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/ tests/conftest.py tests/test_api.py
git commit -m "feat: FastAPI app with health endpoint and dependency injection"
```

---

### Task 10: Entries Router

**Files:**
- Create: `foodlog/api/routers/entries.py`
- Modify: `foodlog/api/app.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
import datetime


def test_create_entry(client):
    resp = client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken Breast",
                "quantity": 1.0,
                "unit": "serving",
                "weight_g": 150.0,
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "source_id": "33691",
                "raw_input": "grilled chicken breast",
            }
        ],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 1
    assert data[0]["food_name"] == "Chicken Breast"
    assert data[0]["id"] is not None


def test_get_entries_today(client):
    client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken Breast",
                "quantity": 1.0,
                "unit": "serving",
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "raw_input": "chicken",
            }
        ],
    )
    resp = client.get("/entries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


def test_get_entries_filter_meal_type(client):
    client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken",
                "quantity": 1.0,
                "unit": "serving",
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "raw_input": "chicken",
            }
        ],
    )
    resp = client.get("/entries", params={"meal_type": "dinner"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_update_entry(client):
    create_resp = client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken",
                "quantity": 1.0,
                "unit": "serving",
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "raw_input": "chicken",
            }
        ],
    )
    entry_id = create_resp.json()[0]["id"]

    resp = client.put(f"/entries/{entry_id}", json={"quantity": 2.0, "calories": 495.0})
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 2.0
    assert resp.json()["calories"] == 495.0


def test_update_nonexistent_entry(client):
    resp = client.put("/entries/999", json={"quantity": 2.0})
    assert resp.status_code == 404


def test_delete_entry(client):
    create_resp = client.post(
        "/entries",
        json=[
            {
                "meal_type": "snack",
                "food_name": "Apple",
                "quantity": 1.0,
                "unit": "medium",
                "calories": 95.0,
                "protein_g": 0.5,
                "carbs_g": 25.0,
                "fat_g": 0.3,
                "source": "usda",
                "raw_input": "apple",
            }
        ],
    )
    entry_id = create_resp.json()[0]["id"]

    resp = client.delete(f"/entries/{entry_id}")
    assert resp.status_code == 204

    resp = client.get("/entries")
    assert resp.json() == []


def test_delete_nonexistent_entry(client):
    resp = client.delete("/entries/999")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_api.py::test_create_entry -v`

Expected: FAIL — 404 (route not mounted)

- [ ] **Step 3: Create entries router**

Create `foodlog/api/routers/entries.py`:

```python
import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.models.schemas import (
    FoodEntryCreate,
    FoodEntryResponse,
    FoodEntryUpdate,
)
from foodlog.services.logging import EntryService

router = APIRouter(prefix="/entries", tags=["entries"])


@router.post("", status_code=201, response_model=list[FoodEntryResponse])
def create_entries(
    entries: list[FoodEntryCreate],
    db: Session = Depends(get_db),
):
    svc = EntryService(db)
    return svc.create_many(entries)


@router.get("", response_model=list[FoodEntryResponse])
def get_entries(
    date: datetime.date | None = None,
    meal_type: str | None = None,
    db: Session = Depends(get_db),
):
    svc = EntryService(db)
    target_date = date or datetime.date.today()
    return svc.get_by_date(target_date, meal_type=meal_type)


@router.put("/{entry_id}", response_model=FoodEntryResponse)
def update_entry(
    entry_id: int,
    data: FoodEntryUpdate,
    db: Session = Depends(get_db),
):
    svc = EntryService(db)
    entry = svc.update(entry_id, data)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.delete("/{entry_id}", status_code=204)
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
):
    svc = EntryService(db)
    if not svc.delete(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return Response(status_code=204)
```

- [ ] **Step 4: Mount the router in app.py**

Add to `foodlog/api/app.py`, inside `create_app()`, before `return app`:

```python
    from foodlog.api.routers.entries import router as entries_router

    app.include_router(entries_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_api.py -v`

Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/entries.py foodlog/api/app.py tests/test_api.py
git commit -m "feat: entries CRUD router"
```

---

### Task 11: Summary Router

**Files:**
- Create: `foodlog/api/routers/summary.py`
- Modify: `foodlog/api/app.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def _seed_entries(client):
    """Helper to create test entries."""
    client.post(
        "/entries",
        json=[
            {
                "meal_type": "lunch",
                "food_name": "Chicken",
                "quantity": 1.0,
                "unit": "serving",
                "calories": 247.5,
                "protein_g": 46.5,
                "carbs_g": 0.0,
                "fat_g": 5.4,
                "source": "fatsecret",
                "raw_input": "chicken",
            },
            {
                "meal_type": "lunch",
                "food_name": "Rice",
                "quantity": 1.5,
                "unit": "cup",
                "calories": 340.0,
                "protein_g": 6.0,
                "carbs_g": 74.0,
                "fat_g": 1.0,
                "source": "fatsecret",
                "raw_input": "rice",
            },
        ],
    )


def test_daily_summary(client):
    _seed_entries(client)
    resp = client.get("/summary/daily")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calories"] == 587.5
    assert data["total_protein_g"] == 52.5
    assert len(data["meals"]) == 1
    assert data["meals"][0]["entry_count"] == 2


def test_daily_summary_empty(client):
    resp = client.get("/summary/daily")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calories"] == 0.0
    assert data["meals"] == []


def test_range_summary(client):
    _seed_entries(client)
    today = datetime.date.today().isoformat()
    resp = client.get("/summary/range", params={"start": today, "end": today})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calories"] == 587.5
    assert data["days"] == 1
    assert data["avg_daily_calories"] == 587.5
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_api.py::test_daily_summary -v`

Expected: FAIL — 404 (route not mounted)

- [ ] **Step 3: Create summary router**

Create `foodlog/api/routers/summary.py`:

```python
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.models.schemas import DailySummary, RangeSummary
from foodlog.services.nutrition import SummaryService

router = APIRouter(prefix="/summary", tags=["summary"])


@router.get("/daily", response_model=DailySummary)
def daily_summary(
    date: datetime.date | None = None,
    db: Session = Depends(get_db),
):
    svc = SummaryService(db)
    return svc.daily(date or datetime.date.today())


@router.get("/range", response_model=RangeSummary)
def range_summary(
    start: datetime.date,
    end: datetime.date,
    db: Session = Depends(get_db),
):
    svc = SummaryService(db)
    return svc.range(start, end)
```

- [ ] **Step 4: Mount the router in app.py**

Add to `foodlog/api/app.py`, inside `create_app()`, before `return app`:

```python
    from foodlog.api.routers.summary import router as summary_router

    app.include_router(summary_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_api.py -v`

Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/summary.py foodlog/api/app.py tests/test_api.py
git commit -m "feat: summary router with daily and range endpoints"
```

---

### Task 12: Foods Router (Search)

**Files:**
- Create: `foodlog/api/routers/foods.py`
- Modify: `foodlog/api/app.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
from unittest.mock import AsyncMock, patch

from foodlog.models.schemas import FoodSearchResult


def test_search_foods(client):
    mock_results = [
        FoodSearchResult(
            food_id="33691",
            food_name="Chicken Breast",
            source="fatsecret",
            calories=165.0,
            protein_g=31.0,
            carbs_g=0.0,
            fat_g=3.6,
            serving_description="Per 100g",
        )
    ]

    with patch(
        "foodlog.api.routers.foods.get_search_service"
    ) as mock_get_svc:
        mock_svc = AsyncMock()
        mock_svc.search.return_value = mock_results
        mock_get_svc.return_value = mock_svc

        resp = client.get("/foods/search", params={"q": "chicken"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["food_name"] == "Chicken Breast"


def test_search_foods_missing_query(client):
    resp = client.get("/foods/search")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_api.py::test_search_foods -v`

Expected: FAIL — 404 (route not mounted)

- [ ] **Step 3: Create foods router**

Create `foodlog/api/routers/foods.py`:

```python
from fastapi import APIRouter, Query

from foodlog.api.dependencies import get_fatsecret_client, get_usda_client
from foodlog.models.schemas import FoodSearchResult
from foodlog.services.search import SearchService

router = APIRouter(prefix="/foods", tags=["foods"])


def get_search_service() -> SearchService:
    return SearchService(
        fatsecret=get_fatsecret_client(),
        usda=get_usda_client(),
    )


@router.get("/search", response_model=list[FoodSearchResult])
async def search_foods(
    q: str = Query(..., description="Food search query"),
):
    svc = get_search_service()
    return await svc.search(q)
```

- [ ] **Step 4: Mount the router in app.py**

Add to `foodlog/api/app.py`, inside `create_app()`, before `return app`:

```python
    from foodlog.api.routers.foods import router as foods_router

    app.include_router(foods_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_api.py -v`

Expected: 13 passed

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/foods.py foodlog/api/app.py tests/test_api.py
git commit -m "feat: food search router with FatSecret/USDA fallback"
```

---

### Task 13: MCP Server

**Files:**
- Create: `mcp_server/__init__.py`
- Create: `mcp_server/server.py`
- Create: `tests/test_mcp.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp.py`:

```python
import pytest
from mcp.server.fastmcp import FastMCP

from mcp_server.server import create_mcp_server


def test_mcp_server_has_tools():
    mcp = create_mcp_server()
    assert isinstance(mcp, FastMCP)
    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "search_food" in tool_names
    assert "log_food" in tool_names
    assert "get_entries" in tool_names
    assert "edit_entry" in tool_names
    assert "delete_entry" in tool_names
    assert "get_daily_summary" in tool_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_mcp.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_server'`

- [ ] **Step 3: Implement MCP server**

Create `mcp_server/__init__.py` (empty) and `mcp_server/server.py`:

```python
import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_BASE_URL = "http://127.0.0.1:8042"


def create_mcp_server(base_url: str = DEFAULT_BASE_URL) -> FastMCP:
    mcp = FastMCP(
        "FoodLog",
        instructions=(
            "Food logging assistant. Use search_food to find nutrition data, "
            "then log_food to record meals. Use get_daily_summary to show totals. "
            "Always search before logging to get accurate nutrition values."
        ),
    )

    @mcp.tool()
    async def search_food(query: str) -> list[dict]:
        """Search the nutrition database for a food item.

        Returns matches with calories and macros per serving.
        Use this to find the right database match before logging.

        Args:
            query: Food name to search for (e.g. "chicken breast", "oat milk latte")
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base_url}/foods/search", params={"q": query}
            )
            resp.raise_for_status()
            return resp.json()

    @mcp.tool()
    async def log_food(entries: list[dict]) -> list[dict]:
        """Log one or more food items to the diary.

        Use after searching to include accurate nutrition data.
        Include the original user description in raw_input.

        Args:
            entries: Array of food entry objects. Each must include:
                meal_type (breakfast/lunch/dinner/snack), food_name, quantity,
                unit, calories, protein_g, carbs_g, fat_g, source, raw_input.
                Optional: weight_g, source_id, fiber_g, sugar_g, sodium_mg.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{base_url}/entries", json=entries)
            resp.raise_for_status()
            return resp.json()

    @mcp.tool()
    async def get_entries(date: str | None = None, meal_type: str | None = None) -> list[dict]:
        """Get food diary entries. Defaults to today.

        Use to show the user what they've logged or to check before adding duplicates.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
            meal_type: Filter by meal type (breakfast/lunch/dinner/snack)
        """
        params = {}
        if date:
            params["date"] = date
        if meal_type:
            params["meal_type"] = meal_type
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/entries", params=params)
            resp.raise_for_status()
            return resp.json()

    @mcp.tool()
    async def edit_entry(entry_id: int, updates: dict) -> dict:
        """Update a previously logged entry.

        Fix quantity, swap to a better match, change meal type.

        Args:
            entry_id: ID of the entry to update
            updates: Fields to update (e.g. {"quantity": 2.0, "calories": 495.0})
        """
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{base_url}/entries/{entry_id}", json=updates
            )
            resp.raise_for_status()
            return resp.json()

    @mcp.tool()
    async def delete_entry(entry_id: int) -> str:
        """Remove a food entry from the diary.

        Args:
            entry_id: ID of the entry to delete
        """
        async with httpx.AsyncClient() as client:
            resp = await client.delete(f"{base_url}/entries/{entry_id}")
            resp.raise_for_status()
            return f"Entry {entry_id} deleted"

    @mcp.tool()
    async def get_daily_summary(date: str | None = None) -> dict:
        """Get total calories, protein, carbs, and fat for a day, broken down by meal.

        Defaults to today.

        Args:
            date: Date in YYYY-MM-DD format (default: today)
        """
        params = {}
        if date:
            params["date"] = date
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/summary/daily", params=params)
            resp.raise_for_status()
            return resp.json()

    return mcp


if __name__ == "__main__":
    mcp = create_mcp_server()
    mcp.run(transport="stdio")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest tests/test_mcp.py -v`

Expected: 1 passed

Note: If the MCP SDK's internal `_tool_manager` attribute has a different name, adjust the test. The key assertion is that the server object exists and has the expected tools registered. Check with `dir(mcp)` if needed.

- [ ] **Step 5: Commit**

```bash
git add mcp_server/ tests/test_mcp.py
git commit -m "feat: MCP server with 6 food logging tools"
```

---

### Task 14: MCP Registration + Server Entrypoint

**Files:**
- Create: `.mcp.json`
- Modify: `foodlog/api/app.py` (add `__main__` runner)

- [ ] **Step 1: Create .mcp.json**

Create `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "foodlog": {
      "command": "/home/ryan/foodlog/.venv/bin/python",
      "args": ["/home/ryan/foodlog/mcp_server/server.py"]
    }
  }
}
```

- [ ] **Step 2: Add API server entrypoint**

Add to the bottom of `foodlog/api/app.py`:

```python
if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=settings.foodlog_host, port=settings.foodlog_port)
```

- [ ] **Step 3: Verify the API server starts**

Run:
```bash
cd /home/ryan/foodlog && source .venv/bin/activate
timeout 5 python -m foodlog.api.app || true
```

Expected: Server starts on 127.0.0.1:8042 (killed by timeout after 5s). If there's an import error, fix it.

Note: You may need to adjust to run via `python foodlog/api/app.py` or add a `__main__.py`. The key is that the server starts without errors.

- [ ] **Step 4: Run full test suite**

Run: `cd /home/ryan/foodlog && source .venv/bin/activate && pytest -v`

Expected: All tests pass (approximately 20+ tests).

- [ ] **Step 5: Commit**

```bash
git add .mcp.json foodlog/api/app.py
git commit -m "feat: MCP registration and API server entrypoint"
```

---

### Task 15: End-to-End Smoke Test

**Files:**
- No new files. This task verifies the full stack works.

- [ ] **Step 1: Start the API server in the background**

```bash
cd /home/ryan/foodlog && source .venv/bin/activate
python foodlog/api/app.py &
API_PID=$!
sleep 2
```

- [ ] **Step 2: Test health endpoint**

```bash
curl -s http://127.0.0.1:8042/health | python -m json.tool
```

Expected:
```json
{
    "status": "ok",
    "fatsecret": false,
    "usda": false
}
```

(false because no API keys are configured yet — this is correct)

- [ ] **Step 3: Test entry creation via curl**

```bash
curl -s -X POST http://127.0.0.1:8042/entries \
  -H "Content-Type: application/json" \
  -d '[{"meal_type":"lunch","food_name":"Chicken Breast","quantity":1.0,"unit":"serving","weight_g":150.0,"calories":247.5,"protein_g":46.5,"carbs_g":0.0,"fat_g":5.4,"source":"manual","raw_input":"grilled chicken breast"}]' | python -m json.tool
```

Expected: 201 response with the created entry including an `id`.

- [ ] **Step 4: Test daily summary via curl**

```bash
curl -s http://127.0.0.1:8042/summary/daily | python -m json.tool
```

Expected: Summary showing 247.5 total calories for today.

- [ ] **Step 5: Stop the API server**

```bash
kill $API_PID
```

- [ ] **Step 6: Final commit with any fixes**

If any issues were found and fixed during smoke testing:

```bash
git add -A
git commit -m "fix: smoke test fixes"
```

If no fixes needed, skip this step.

---

## Post-Implementation Notes

After all tasks are complete:

1. **Get API keys:** Register at platform.fatsecret.com and api.data.gov, add keys to `.env`
2. **Register MCP with Claude Code:** Run `claude mcp add foodlog -- /home/ryan/foodlog/.venv/bin/python /home/ryan/foodlog/mcp_server/server.py` or copy `.mcp.json` to the appropriate scope
3. **Start the API server** before using MCP tools: `cd /home/ryan/foodlog && source .venv/bin/activate && python foodlog/api/app.py`
4. **Test with Claude:** Say "I had scrambled eggs and toast for breakfast" and verify Claude uses the MCP tools to search and log
