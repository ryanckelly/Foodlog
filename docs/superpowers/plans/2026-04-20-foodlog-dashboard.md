# FoodLog Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a local, secure Dashboard using FastAPI, Jinja2, and HTMX to display chronological logs and macro summaries.

**Architecture:** We are serving HTML directly from the FastAPI application. We'll use HTMX to dynamically load a daily/range timeline and summary partial into a base layout powered by a lightweight CSS framework via CDN (Pico.css).

**Tech Stack:** Python, FastAPI, Jinja2, HTMX, Pico.css

---

### Task 1: Add Frontend Dependencies

**Files:**
- Modify: `pyproject.toml:13-22`

- [ ] **Step 1: Add `jinja2` to dependencies**

```toml
    "pydantic-settings>=2.0.0",
    "httpx>=0.27.0",
    "mcp[cli]>=1.2.0",
    "python-dotenv>=1.0.0",
    "jinja2>=3.1.0",
]
```

- [ ] **Step 2: Install updated dependencies**

Run: `pip install -e ".[dev]"`
Expected: PASS with Jinja2 installed.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add jinja2 for frontend templates"
```

---

### Task 2: Extend EntryService for Date Ranges

**Files:**
- Modify: `foodlog/services/logging.py`
- Modify: `tests/test_services.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_services.py`:
```python
def test_get_by_range(db_session, sample_food_entries):
    from foodlog.services.logging import EntryService
    import datetime
    
    svc = EntryService(db_session)
    start_date = datetime.date.today() - datetime.timedelta(days=1)
    end_date = datetime.date.today()
    
    entries = svc.get_by_range(start_date, end_date)
    assert len(entries) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_services.py::test_get_by_range -v`
Expected: FAIL with "AttributeError: 'EntryService' object has no attribute 'get_by_range'"

- [ ] **Step 3: Write minimal implementation**

Add to `EntryService` in `foodlog/services/logging.py` (below `get_by_date`):
```python
    def get_by_range(
        self, start_date: datetime.date, end_date: datetime.date, meal_type: str | None = None
    ) -> list[FoodEntry]:
        query = self.session.query(FoodEntry).filter(
            func.date(FoodEntry.logged_at) >= start_date,
            func.date(FoodEntry.logged_at) <= end_date
        )
        if meal_type:
            query = query.filter(FoodEntry.meal_type == meal_type)
        return query.order_by(FoodEntry.logged_at.desc()).all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_services.py::test_get_by_range -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add foodlog/services/logging.py tests/test_services.py
git commit -m "feat: add get_by_range to EntryService"
```

---

### Task 3: Base Layout & Dashboard Template

**Files:**
- Create: `foodlog/templates/base.html`
- Create: `foodlog/templates/dashboard/index.html`

- [ ] **Step 1: Create the base template**

Create `foodlog/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FoodLog Dashboard</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <style>
        .macro-pill {
            display: inline-block;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.85em;
            background: #f1f5f9;
            color: #334155;
            margin-right: 0.25rem;
        }
    </style>
</head>
<body>
    <main class="container">
        <nav>
            <ul>
                <li><strong>FoodLog</strong></li>
            </ul>
        </nav>
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 2: Create the dashboard index template**

Create `foodlog/templates/dashboard/index.html`:
```html
{% extends "base.html" %}

{% block content %}
<section>
    <div class="grid">
        <div>
            <h2>Dashboard</h2>
        </div>
        <div style="text-align: right;">
            <select name="date_range" hx-get="/dashboard/feed" hx-target="#dashboard-content" hx-trigger="change, load">
                <option value="today">Today</option>
                <option value="yesterday">Yesterday</option>
                <option value="week">This Week</option>
            </select>
        </div>
    </div>
</section>

<div id="dashboard-content">
    <article aria-busy="true"></article>
</div>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add foodlog/templates/
git commit -m "feat: add base layout and dashboard index template"
```

---

### Task 4: HTMX Partials

**Files:**
- Create: `foodlog/templates/dashboard/feed_partial.html`

- [ ] **Step 1: Create the feed partial template**

Create `foodlog/templates/dashboard/feed_partial.html`:
```html
<div class="grid">
    <div>
        <article>
            <header>
                <strong>Timeline</strong>
            </header>
            {% if entries %}
                {% for entry in entries %}
                <div style="padding: 10px; border: 1px solid #e2e8f0; border-radius: 6px; margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between;">
                        <span><strong>{{ entry.food_name }}</strong> ({{ entry.quantity }} {{ entry.unit }})</span>
                        <span><strong>{{ entry.calories | round }} kcal</strong></span>
                    </div>
                    <div style="color: #64748b; font-size: 0.9em;">
                        {{ entry.logged_at.strftime('%I:%M %p') }} - {{ entry.meal_type | title }}
                    </div>
                    <div style="margin-top: 5px;">
                        <span class="macro-pill">P: {{ entry.protein_g | round }}g</span>
                        <span class="macro-pill">C: {{ entry.carbs_g | round }}g</span>
                        <span class="macro-pill">F: {{ entry.fat_g | round }}g</span>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <p>No entries found for this period.</p>
            {% endif %}
        </article>
    </div>
    <div>
        <article>
            <header>
                <strong>Summary</strong>
            </header>
            <ul>
                <li>Total Calories: <strong>{{ summary.total_calories | round }}</strong></li>
                <li>Protein: <strong>{{ summary.total_protein_g | round }}g</strong></li>
                <li>Carbs: <strong>{{ summary.total_carbs_g | round }}g</strong></li>
                <li>Fat: <strong>{{ summary.total_fat_g | round }}g</strong></li>
            </ul>
        </article>
    </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add foodlog/templates/dashboard/feed_partial.html
git commit -m "feat: add feed partial template for dashboard"
```

---

### Task 5: Dashboard Router

**Files:**
- Create: `foodlog/api/routers/dashboard.py`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard.py`:
```python
import pytest
from fastapi.testclient import TestClient

def test_dashboard_index(client: TestClient):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "FoodLog Dashboard" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Write minimal implementation**

Create `foodlog/api/routers/dashboard.py`:
```python
import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.services.logging import EntryService
from foodlog.services.nutrition import SummaryService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="foodlog/templates")

@router.get("", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("dashboard/index.html", {"request": request})

@router.get("/feed", response_class=HTMLResponse)
def feed_partial(
    request: Request,
    date_range: str = "today",
    db: Session = Depends(get_db)
):
    entry_svc = EntryService(db)
    summary_svc = SummaryService(db)
    
    today = datetime.date.today()
    if date_range == "yesterday":
        start_date = today - datetime.timedelta(days=1)
        end_date = start_date
    elif date_range == "week":
        start_date = today - datetime.timedelta(days=7)
        end_date = today
    else:
        start_date = today
        end_date = today
        
    if start_date == end_date:
        entries = entry_svc.get_by_date(start_date)
        summary = summary_svc.daily(start_date)
    else:
        entries = entry_svc.get_by_range(start_date, end_date)
        summary = summary_svc.range(start_date, end_date)
        
    return templates.TemplateResponse(
        "dashboard/feed_partial.html", 
        {
            "request": request, 
            "entries": entries, 
            "summary": summary
        }
    )
```

- [ ] **Step 4: Register in app**

Modify `foodlog/api/app.py` directly under where the other routers are imported. Add:
```python
    from foodlog.api.routers.dashboard import router as dashboard_router
    app.include_router(dashboard_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add foodlog/api/routers/dashboard.py foodlog/api/app.py tests/test_dashboard.py
git commit -m "feat: add dashboard router and endpoints"
```
