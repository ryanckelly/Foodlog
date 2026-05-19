# Body-Composition Simulator — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the full body-composition simulator pipeline using population-default parameters — produces a runnable Jupyter notebook with `ipywidgets` sliders for scenario exploration, plus diagnostic validation against the user's actual 14 weigh-ins.

**Architecture:** New `body_sim/` Python package (top-level sibling of `foodlog/` and `mcp_server/`) holding pure-function mechanistic modules (Keytel HR-to-kcal, Hall energy balance, Forbes partitioning, glycogen/sodium water dynamics) plus a state-space scenario simulator. Five new Jupyter notebooks at top-level `notebooks/` consume the package. Tests live at `tests/body_sim/` following the existing in-memory-SQLite pattern from `tests/conftest.py`.

**Tech Stack:** Python 3.12, NumPy, pandas, SciPy (statistics only), matplotlib, ipywidgets, Jupyter, SQLAlchemy 2.0 (read-only against the existing foodlog DB), pytest. **No PyMC at Phase 1** — Bayesian fitting starts at Phase 2 (`foodlog-j90`). Population priors are sampled with `numpy.random` for uncertainty bands.

**Spec reference:** `docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md`

**Beads tracked under:** `foodlog-jok` (Phase 1 epic). Parallel-track enhancement beads (`foodlog-taq` sleep stages, `foodlog-b1f` submission_id, `foodlog-fkn` consumed_at, `foodlog-jav` Pixel Watch discovery) are **not** part of this plan — they can land at any time and the pipeline absorbs new columns transparently.

---

## File structure

### New files

```
body_sim/                              # new top-level package
  __init__.py                          # version + public surface
  config.py                            # user_profile (age, sex, height); literature constants
  keytel.py                            # HR(t) → kcal/min; daily integration
  rmr.py                               # Mifflin-St Jeor RMR
  glycogen.py                          # carb → glycogen → bound water
  sodium.py                            # sodium → water
  partition.py                         # Forbes p; protein_protection modifier
  adaptation.py                        # adaptive thermogenesis term
  tef.py                               # thermic effect of food per macro
  model.py                             # one-day state update
  pipeline.py                          # SQLite → daily-rollup pandas DataFrame
  simulate.py                          # forward-simulate N days with uncertainty
  validation.py                        # forward-walking harness
  evaluate.py                          # MAE, calibration coverage, residual stats
  plotting.py                          # the three required validation plots
  README.md                            # package overview

notebooks/                             # new top-level directory
  02_data_pipeline.ipynb
  03_descriptive_eda.ipynb
  04_hall_baseline.ipynb
  06_scenario_simulator.ipynb
  07_live_tracking.ipynb
  predictions/                         # output dir for live-tracking forecasts
    .gitkeep

tests/body_sim/                        # new
  __init__.py
  conftest.py                          # synthetic-data fixtures (in-memory SQLite)
  test_keytel.py
  test_rmr.py
  test_glycogen.py
  test_sodium.py
  test_partition.py
  test_adaptation.py
  test_tef.py
  test_model.py
  test_pipeline.py
  test_simulate.py
  test_validation.py
  test_evaluate.py
  test_plotting.py
```

### Modified files

```
pyproject.toml                                                   # add body_sim package + body_sim dev deps
docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md  # reconcile path: src/body_sim → body_sim
```

### Path convention

All modules under `body_sim/` are pure functions where possible. The single SQLite-aware module is `pipeline.py`, which takes a SQLAlchemy session as a parameter — never opens a connection itself. This keeps tests in-memory-fast.

Notebooks anchor paths to the project root via `_repo_root = Path.cwd()` at the top of each notebook (the convention is to launch Jupyter from `/opt/foodlog/`). Predictions persist as JSON-Lines under `notebooks/predictions/`.

---

## Task 1: Scaffolding and package config

**Files:**
- Create: `body_sim/__init__.py`
- Create: `body_sim/README.md`
- Create: `tests/body_sim/__init__.py`
- Create: `tests/body_sim/conftest.py`
- Create: `notebooks/.gitkeep`
- Create: `notebooks/predictions/.gitkeep`
- Modify: `pyproject.toml` (add package + dev deps)
- Modify: `docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md` (path reconciliation)

- [ ] **Step 1: Create empty package files**

```bash
mkdir -p body_sim tests/body_sim notebooks/predictions
touch body_sim/__init__.py tests/body_sim/__init__.py notebooks/predictions/.gitkeep
```

- [ ] **Step 2: Write `body_sim/__init__.py`**

```python
"""Body-composition scenario simulator.

A mechanistic energy-balance model (Hall et al. extended) for simulating
counterfactual diet/exercise scenarios. Designed for notebook-driven research
on top of the foodlog database. Phase 1 uses population-default parameters;
Phase 2 personalizes via PyMC Bayesian inference.

See docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md
for the design.
"""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write `body_sim/README.md`**

```markdown
# body_sim

Body-composition scenario simulator. Mechanistic energy-balance model with
Bayesian personalization, consumed by notebooks under `notebooks/`.

See the design spec for full architecture:
`docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md`

## Module map

| Module | Role |
|---|---|
| `config.py` | User profile (age, sex, height) + literature-default constants |
| `keytel.py` | HR(t) → kcal/min; daily integration |
| `rmr.py` | Mifflin-St Jeor resting metabolic rate |
| `tef.py` | Thermic effect of food per macro |
| `glycogen.py` | Carb intake → glycogen → bound water |
| `sodium.py` | Sodium intake → water retention |
| `partition.py` | Forbes p; protein-protection modifier |
| `adaptation.py` | Adaptive thermogenesis |
| `model.py` | One-day state update composing the above |
| `pipeline.py` | SQLite → daily-rollup pandas DataFrame |
| `simulate.py` | Forward-simulate N days with uncertainty bands |
| `validation.py` | Forward-walking validation harness |
| `evaluate.py` | MAE, calibration coverage, residual diagnostics |
| `plotting.py` | The three required validation plots |

## Running

From the project root:

```bash
pip install -e ".[body_sim]"
jupyter notebook --notebook-dir=notebooks --port 7777
```

Tests:

```bash
pytest tests/body_sim/ -v
```
```

- [ ] **Step 4: Add `body_sim` to `pyproject.toml` packages and a new `body_sim` optional-deps group**

In `pyproject.toml`, modify the `[tool.setuptools]` packages list to include `"body_sim"`, and add a new optional-dependencies group:

```toml
[tool.setuptools]
packages = ["foodlog", "foodlog.api", "foodlog.api.routers", "foodlog.clients", "foodlog.db", "foodlog.models", "foodlog.services", "mcp_server", "body_sim"]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-httpx>=0.30.0",
    "respx>=0.22.0",
]
body_sim = [
    "numpy>=1.26.0",
    "pandas>=2.2.0",
    "scipy>=1.13.0",
    "matplotlib>=3.8.0",
    "ipywidgets>=8.1.0",
    "jupyter>=1.0.0",
]
```

Keep the existing `dev` group as-is.

- [ ] **Step 5: Install the new optional deps and verify**

```bash
pip install -e ".[dev,body_sim]"
python -c "import body_sim; print(body_sim.__version__)"
```

Expected output: `0.1.0`

- [ ] **Step 6: Reconcile spec path convention**

Edit `docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md`. In the "Repository layout" section, replace every occurrence of `src/body_sim/` with `body_sim/` (the actual chosen layout — flat top-level matches foodlog/ and mcp_server/ siblings; the `src/` prefix from the hockey reference project does not match this repo's convention).

Add this note at the end of the Repository layout section:

```markdown
**Layout note:** This deviates from the hockey reference project's `src/` convention because foodlog's existing pattern is top-level packages (`foodlog/`, `mcp_server/`). Keeping `body_sim/` at the top level matches the repo and avoids mixing src-layout and flat-layout in one `pyproject.toml`.
```

- [ ] **Step 7: Write `tests/body_sim/conftest.py` with shared fixtures**

```python
"""Shared fixtures for body_sim tests.

Uses in-memory SQLite (StaticPool) to avoid file I/O during tests, following
the pattern in tests/conftest.py for the main foodlog app.
"""

import datetime
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from foodlog.db.models import Base


@pytest.fixture
def session() -> Iterator[Session]:
    """In-memory SQLite session with the full foodlog schema."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def user_profile() -> dict:
    """Population-default user profile for tests.

    Matches body_sim.config.DEFAULT_PROFILE so tests are reproducible.
    """
    return {
        "age": 40,
        "sex": "male",
        "height_cm": 180,
    }


@pytest.fixture
def reference_date() -> datetime.date:
    """A fixed reference date for deterministic tests."""
    return datetime.date(2026, 5, 1)
```

- [ ] **Step 8: Verify pytest discovers the new test directory**

```bash
pytest tests/body_sim/ -v --collect-only
```

Expected: `collected 0 items` (no test files yet — just confirms discovery works without errors).

- [ ] **Step 9: Commit scaffolding**

```bash
git add body_sim tests/body_sim notebooks pyproject.toml \
        docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md
git commit -m "feat(body_sim): scaffold body_sim package and test layout

- body_sim/ top-level package (flat layout matching foodlog/ + mcp_server/)
- tests/body_sim/ with in-memory SQLite conftest
- notebooks/ + notebooks/predictions/ directories
- pyproject.toml: add body_sim package + optional-dependencies group
- spec: reconcile path convention from src/body_sim to body_sim"
```

---

## Task 2: User-profile config and literature constants

**Files:**
- Create: `body_sim/config.py`
- Test: `tests/body_sim/test_config.py`

This module holds the single user's profile (age, sex, height) and the literature constants used by every other module. Centralizing them here makes Phase 2 personalization a single-file change later.

- [ ] **Step 1: Write the failing test**

Create `tests/body_sim/test_config.py`:

```python
from body_sim import config


def test_default_profile_has_required_fields():
    profile = config.DEFAULT_PROFILE
    assert "age" in profile
    assert "sex" in profile
    assert "height_cm" in profile
    assert profile["sex"] in ("male", "female")


def test_default_parameters_are_population_means():
    params = config.DEFAULT_PARAMETERS
    assert params["intake_bias"] == 0.85
    assert params["RMR_scale"] == 1.0
    assert params["NEAT_response"] == 0.2
    assert params["protein_protection"] == 0.5
    assert params["activity_bias"] == 1.0
    assert params["water_noise_sd"] > 0


def test_tef_coefficients_match_spec():
    coeffs = config.TEF_COEFFICIENTS
    assert coeffs["protein"] == 0.25
    assert coeffs["carb"] == 0.08
    assert coeffs["fat"] == 0.03


def test_glycogen_water_ratio():
    assert config.GLYCOGEN_WATER_G_PER_G == 3.5
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/body_sim/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'body_sim.config'`

- [ ] **Step 3: Implement `body_sim/config.py`**

```python
"""User profile and literature-default constants for body_sim.

All constants here are population averages drawn from the literature, used
as priors / defaults at Phase 1. Phase 2 replaces a subset (intake_bias,
RMR_scale, etc.) with personalized posterior samples.
"""

from typing import TypedDict


class UserProfile(TypedDict):
    age: int
    sex: str  # "male" or "female"
    height_cm: float


DEFAULT_PROFILE: UserProfile = {
    "age": 40,
    "sex": "male",
    "height_cm": 180.0,
}


DEFAULT_PARAMETERS: dict[str, float] = {
    "intake_bias": 0.85,        # 15% under-reporting prior mean
    "RMR_scale": 1.0,
    "NEAT_response": 0.2,
    "protein_protection": 0.5,
    "activity_bias": 1.0,
    "water_noise_sd": 0.8,      # kg
}


TEF_COEFFICIENTS: dict[str, float] = {
    "protein": 0.25,
    "carb": 0.08,
    "fat": 0.03,
}


GLYCOGEN_WATER_G_PER_G: float = 3.5

KCAL_PER_KG_FAT: float = 9500.0
KCAL_PER_KG_LEAN: float = 7600.0

SODIUM_WATER_KG_PER_GRAM: float = 0.0001  # 0.1g water per mg sodium retained
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_config.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/config.py tests/body_sim/test_config.py
git commit -m "feat(body_sim): add user profile and literature constants"
```

---

## Task 3: Keytel HR-to-kcal equation

**Files:**
- Create: `body_sim/keytel.py`
- Test: `tests/body_sim/test_keytel.py`

The Keytel equation translates a per-minute HR reading into kcal/min during activity. Validated against published values for sanity.

Reference equation (men):
```
kcal/min = (-55.0969 + 0.6309*HR + 0.1988*weight + 0.2017*age) / 4.184
```

Reference (women):
```
kcal/min = (-20.4022 + 0.4472*HR - 0.1263*weight + 0.074*age) / 4.184
```

We clip negative values to 0 (resting HR may produce slightly negative outputs from the formula).

- [ ] **Step 1: Write failing tests for the per-minute equation**

Create `tests/body_sim/test_keytel.py`:

```python
import numpy as np
import pytest

from body_sim import keytel


def test_keytel_per_minute_male_known_value():
    # HR=120, weight=80kg, age=40, male
    # raw = -55.0969 + 0.6309*120 + 0.1988*80 + 0.2017*40
    #     = -55.0969 + 75.708 + 15.904 + 8.068 = 44.5831
    # kcal/min = 44.5831 / 4.184 ≈ 10.66
    result = keytel.kcal_per_min(hr=120, weight_kg=80, age=40, sex="male")
    assert result == pytest.approx(10.66, abs=0.05)


def test_keytel_per_minute_female_known_value():
    # HR=120, weight=70kg, age=40, female
    # raw = -20.4022 + 0.4472*120 - 0.1263*70 + 0.074*40
    #     = -20.4022 + 53.664 - 8.841 + 2.96 = 27.3808
    # kcal/min = 27.3808 / 4.184 ≈ 6.54
    result = keytel.kcal_per_min(hr=120, weight_kg=70, age=40, sex="female")
    assert result == pytest.approx(6.54, abs=0.05)


def test_keytel_per_minute_clips_negative():
    # At very low HR the formula goes negative; should clip to 0
    result = keytel.kcal_per_min(hr=40, weight_kg=80, age=40, sex="male")
    assert result >= 0


def test_keytel_per_minute_rejects_invalid_sex():
    with pytest.raises(ValueError):
        keytel.kcal_per_min(hr=120, weight_kg=80, age=40, sex="other")


def test_keytel_daily_integral_constant_hr():
    # 1440 minutes at HR=120 should produce 1440 * per-minute value
    hrs = np.full(1440, 120, dtype=float)
    total = keytel.daily_integral(hrs, weight_kg=80, age=40, sex="male")
    expected = 1440 * keytel.kcal_per_min(120, 80, 40, "male")
    assert total == pytest.approx(expected, abs=1.0)


def test_keytel_daily_integral_handles_nan():
    # Partial-coverage day: some minutes have NaN HR
    hrs = np.full(1440, 120, dtype=float)
    hrs[:720] = np.nan  # first half missing
    total = keytel.daily_integral(hrs, weight_kg=80, age=40, sex="male")
    # Should integrate only over the 720 non-NaN minutes
    expected = 720 * keytel.kcal_per_min(120, 80, 40, "male")
    assert total == pytest.approx(expected, abs=1.0)


def test_keytel_coverage_pct():
    hrs = np.full(1440, 120, dtype=float)
    hrs[:720] = np.nan
    assert keytel.coverage_pct(hrs) == pytest.approx(50.0, abs=0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_keytel.py -v
```

Expected: `ModuleNotFoundError: No module named 'body_sim.keytel'`

- [ ] **Step 3: Implement `body_sim/keytel.py`**

```python
"""Keytel HR-to-kcal equation, validated against indirect calorimetry.

Keytel et al. 2005, J Sports Sci.
"""

import numpy as np


def kcal_per_min(hr: float, weight_kg: float, age: int, sex: str) -> float:
    """Energy expenditure per minute at the given heart rate.

    Args:
        hr: heart rate in BPM
        weight_kg: body weight in kg
        age: years
        sex: "male" or "female"

    Returns:
        kcal/min, clipped to >= 0.
    """
    if sex == "male":
        raw = -55.0969 + 0.6309 * hr + 0.1988 * weight_kg + 0.2017 * age
    elif sex == "female":
        raw = -20.4022 + 0.4472 * hr - 0.1263 * weight_kg + 0.074 * age
    else:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    return max(0.0, raw / 4.184)


def daily_integral(
    hr_minutes: np.ndarray, weight_kg: float, age: int, sex: str
) -> float:
    """Integrate Keytel over a day of minute-level HR values.

    NaN values are skipped (treated as 'watch not worn'), not zeroed.

    Args:
        hr_minutes: array of HR values, one per minute, length up to 1440. NaN where missing.
        weight_kg, age, sex: as for kcal_per_min

    Returns:
        Total kcal across the non-NaN minutes.
    """
    if sex == "male":
        raw = -55.0969 + 0.6309 * hr_minutes + 0.1988 * weight_kg + 0.2017 * age
    elif sex == "female":
        raw = -20.4022 + 0.4472 * hr_minutes - 0.1263 * weight_kg + 0.074 * age
    else:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    per_min = np.clip(raw / 4.184, 0.0, None)
    return float(np.nansum(per_min))


def coverage_pct(hr_minutes: np.ndarray) -> float:
    """Fraction of the day with non-NaN HR data, as a percentage."""
    if len(hr_minutes) == 0:
        return 0.0
    non_nan = np.isfinite(hr_minutes).sum()
    return 100.0 * non_nan / len(hr_minutes)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_keytel.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/keytel.py tests/body_sim/test_keytel.py
git commit -m "feat(body_sim): Keytel HR-to-kcal equation with daily integration"
```

---

## Task 4: Mifflin-St Jeor resting metabolic rate

**Files:**
- Create: `body_sim/rmr.py`
- Test: `tests/body_sim/test_rmr.py`

Mifflin-St Jeor is the most-validated RMR equation. Standard form:

```
men:   RMR = 10*weight + 6.25*height - 5*age + 5
women: RMR = 10*weight + 6.25*height - 5*age - 161
```

Units: weight in kg, height in cm, age in years, result in kcal/day.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_rmr.py`:

```python
import pytest

from body_sim import rmr


def test_rmr_male_known_value():
    # 80kg, 180cm, 40yr, male
    # = 10*80 + 6.25*180 - 5*40 + 5 = 800 + 1125 - 200 + 5 = 1730
    assert rmr.mifflin_st_jeor(weight_kg=80, height_cm=180, age=40, sex="male") == pytest.approx(1730)


def test_rmr_female_known_value():
    # 70kg, 165cm, 40yr, female
    # = 10*70 + 6.25*165 - 5*40 - 161 = 700 + 1031.25 - 200 - 161 = 1370.25
    assert rmr.mifflin_st_jeor(weight_kg=70, height_cm=165, age=40, sex="female") == pytest.approx(1370.25)


def test_rmr_scales_with_weight():
    a = rmr.mifflin_st_jeor(weight_kg=70, height_cm=180, age=40, sex="male")
    b = rmr.mifflin_st_jeor(weight_kg=80, height_cm=180, age=40, sex="male")
    assert b - a == pytest.approx(100.0)


def test_rmr_rejects_invalid_sex():
    with pytest.raises(ValueError):
        rmr.mifflin_st_jeor(weight_kg=80, height_cm=180, age=40, sex="other")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_rmr.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/rmr.py`**

```python
"""Resting metabolic rate (RMR) via Mifflin-St Jeor.

Mifflin et al. 1990, Am J Clin Nutr.
"""


def mifflin_st_jeor(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    """Mifflin-St Jeor RMR in kcal/day.

    Args:
        weight_kg: total body weight (fat + lean + water) in kg
        height_cm: standing height in cm
        age: years
        sex: "male" or "female"

    Returns:
        Predicted RMR in kcal/day.
    """
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_rmr.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/rmr.py tests/body_sim/test_rmr.py
git commit -m "feat(body_sim): Mifflin-St Jeor resting metabolic rate"
```

---

## Task 5: Thermic effect of food

**Files:**
- Create: `body_sim/tef.py`
- Test: `tests/body_sim/test_tef.py`

```
TEF = 0.25*protein_kcal + 0.08*carb_kcal + 0.03*fat_kcal
```

Coefficients come from `config.TEF_COEFFICIENTS` so Phase 2 can override them.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_tef.py`:

```python
import pytest

from body_sim import tef


def test_tef_zero_intake():
    assert tef.tef_kcal(protein_g=0, carb_g=0, fat_g=0) == 0.0


def test_tef_protein_only():
    # 100g protein = 400 kcal, TEF = 0.25*400 = 100
    assert tef.tef_kcal(protein_g=100, carb_g=0, fat_g=0) == pytest.approx(100.0)


def test_tef_mixed_meal():
    # 150g protein (600 kcal), 200g carb (800 kcal), 60g fat (540 kcal)
    # TEF = 0.25*600 + 0.08*800 + 0.03*540 = 150 + 64 + 16.2 = 230.2
    assert tef.tef_kcal(protein_g=150, carb_g=200, fat_g=60) == pytest.approx(230.2, abs=0.1)


def test_tef_high_carb_vs_high_protein_same_kcal():
    # Same kcal, different macros → different TEF (high-protein burns more)
    hi_protein = tef.tef_kcal(protein_g=150, carb_g=200, fat_g=60)  # ~2000 kcal
    hi_carb = tef.tef_kcal(protein_g=80, carb_g=250, fat_g=80)  # ~2040 kcal, similar
    assert hi_protein > hi_carb
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_tef.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/tef.py`**

```python
"""Thermic effect of food (TEF) per macronutrient.

Coefficients reflect the energy cost of digesting and metabolizing each macro:
protein is most expensive (~25%), carbs intermediate (~8%), fat cheapest (~3%).
Source: Westerterp 2004, Nutr Metab.
"""

from body_sim.config import TEF_COEFFICIENTS

KCAL_PER_G_PROTEIN = 4.0
KCAL_PER_G_CARB = 4.0
KCAL_PER_G_FAT = 9.0


def tef_kcal(protein_g: float, carb_g: float, fat_g: float) -> float:
    """Thermic effect of food given macronutrient intake in grams.

    Returns:
        TEF in kcal/day.
    """
    protein_kcal = protein_g * KCAL_PER_G_PROTEIN
    carb_kcal = carb_g * KCAL_PER_G_CARB
    fat_kcal = fat_g * KCAL_PER_G_FAT
    return (
        TEF_COEFFICIENTS["protein"] * protein_kcal
        + TEF_COEFFICIENTS["carb"] * carb_kcal
        + TEF_COEFFICIENTS["fat"] * fat_kcal
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_tef.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/tef.py tests/body_sim/test_tef.py
git commit -m "feat(body_sim): thermic effect of food per macro"
```

---

## Task 6: Glycogen-water dynamics

**Files:**
- Create: `body_sim/glycogen.py`
- Test: `tests/body_sim/test_glycogen.py`

Carbs are stored as muscle/liver glycogen, which binds water (~3.5 g water per g glycogen). Glycogen turnover is fast (hours-to-days). We model it as a simple leaky integrator:

```
glycogen_{t+1} = glycogen_t + alpha * (carb_g - oxidation_g)
oxidation_g = beta * glycogen_t   # proportional decay
glycogen capped between 0 and ~500g (typical adult capacity)
bound_water_kg = 3.5 * glycogen_g / 1000
```

Population defaults: alpha=0.3 (fraction of dietary carbs stored as glycogen short-term), beta=0.4 (fraction of glycogen oxidized per day).

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_glycogen.py`:

```python
import pytest

from body_sim import glycogen


def test_initial_glycogen_default():
    assert glycogen.INITIAL_GLYCOGEN_G == pytest.approx(400.0, abs=50.0)


def test_water_from_glycogen():
    # 400g glycogen → 1.4 kg water
    assert glycogen.water_kg_from_glycogen(400) == pytest.approx(1.4, abs=0.01)


def test_water_from_zero_glycogen():
    assert glycogen.water_kg_from_glycogen(0) == 0.0


def test_glycogen_update_high_carb_increases():
    # High carb intake, low starting glycogen → glycogen rises
    new = glycogen.update(current_glycogen_g=200, carb_g=400)
    assert new > 200


def test_glycogen_update_low_carb_decreases():
    # Low carb intake, high starting glycogen → glycogen falls
    new = glycogen.update(current_glycogen_g=500, carb_g=50)
    assert new < 500


def test_glycogen_capped_at_max():
    # Massive carb intake doesn't push glycogen past physiological cap
    new = glycogen.update(current_glycogen_g=450, carb_g=2000)
    assert new <= glycogen.MAX_GLYCOGEN_G


def test_glycogen_floored_at_zero():
    # Extended fast can't drive glycogen negative
    new = glycogen.update(current_glycogen_g=10, carb_g=0)
    assert new >= 0


def test_glycogen_steady_state():
    # At alpha*carb = beta*glycogen, glycogen is at equilibrium
    # equilibrium_glycogen = alpha * carb / beta = 0.3 * 200 / 0.4 = 150
    new = glycogen.update(current_glycogen_g=150, carb_g=200)
    assert new == pytest.approx(150, abs=1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_glycogen.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/glycogen.py`**

```python
"""Glycogen-bound water compartment.

Carbohydrate intake is stored as glycogen in muscle and liver. Glycogen binds
approximately 3.5 g of water per gram. This is the dominant cause of short-term
weight fluctuations from diet changes (the 'I lost 3 lbs in two days on keto'
phenomenon is mostly water from glycogen depletion).

We model glycogen as a leaky integrator: a fraction of dietary carbs goes into
storage; a fraction of stored glycogen is oxidized per day.
"""

from body_sim.config import GLYCOGEN_WATER_G_PER_G

# Literature defaults
ALPHA = 0.3        # fraction of dietary carbs into short-term glycogen
BETA = 0.4         # fraction of glycogen oxidized per day
INITIAL_GLYCOGEN_G = 400.0
MAX_GLYCOGEN_G = 600.0


def water_kg_from_glycogen(glycogen_g: float) -> float:
    """Bound water in kg given current glycogen stores."""
    return GLYCOGEN_WATER_G_PER_G * glycogen_g / 1000.0


def update(current_glycogen_g: float, carb_g: float) -> float:
    """One-day glycogen update.

    Args:
        current_glycogen_g: glycogen store at start of day
        carb_g: dietary carb intake during the day

    Returns:
        Glycogen store at end of day, bounded [0, MAX_GLYCOGEN_G].
    """
    new = current_glycogen_g + ALPHA * carb_g - BETA * current_glycogen_g
    return max(0.0, min(MAX_GLYCOGEN_G, new))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_glycogen.py -v
```

Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/glycogen.py tests/body_sim/test_glycogen.py
git commit -m "feat(body_sim): glycogen-bound water dynamics"
```

---

## Task 7: Sodium-water retention

**Files:**
- Create: `body_sim/sodium.py`
- Test: `tests/body_sim/test_sodium.py`

Simple linear model: extra sodium above a baseline drives extra water retention. Decay is fast (1-2 days). We model the *additive deviation* from baseline retention, not absolute body water.

```
sodium_water_kg = SODIUM_WATER_KG_PER_GRAM * max(0, sodium_mg - baseline_mg)
baseline_mg = 2300 (recommended daily intake)
```

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_sodium.py`:

```python
import pytest

from body_sim import sodium


def test_sodium_water_at_baseline_is_zero():
    # At 2300mg/day (baseline), no extra retention
    assert sodium.water_kg(sodium_mg=2300) == 0.0


def test_sodium_water_below_baseline_is_zero():
    # Below baseline doesn't produce negative water
    assert sodium.water_kg(sodium_mg=1500) == 0.0


def test_sodium_water_high_intake():
    # 5300mg = 3000 above baseline; ~0.3 kg extra water
    result = sodium.water_kg(sodium_mg=5300)
    assert 0.1 < result < 1.0


def test_sodium_water_monotonic():
    # More sodium → more water
    a = sodium.water_kg(sodium_mg=3000)
    b = sodium.water_kg(sodium_mg=5000)
    assert b > a
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_sodium.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/sodium.py`**

```python
"""Sodium-bound water retention.

Excess sodium intake above the dietary baseline drives transient water retention
(typical: 100-300 mg water per excess mg sodium). This is a first-order model
of a complex renal process — good enough to explain the 1-2 lb scale jump after
a high-sodium meal but not a clinical sodium-balance model.
"""

from body_sim.config import SODIUM_WATER_KG_PER_GRAM

BASELINE_SODIUM_MG = 2300.0  # WHO-recommended daily intake


def water_kg(sodium_mg: float) -> float:
    """Extra water retention in kg given today's sodium intake."""
    excess_mg = max(0.0, sodium_mg - BASELINE_SODIUM_MG)
    return SODIUM_WATER_KG_PER_GRAM * excess_mg
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_sodium.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/sodium.py tests/body_sim/test_sodium.py
git commit -m "feat(body_sim): sodium-bound water retention"
```

---

## Task 8: Forbes partition and protein protection

**Files:**
- Create: `body_sim/partition.py`
- Test: `tests/body_sim/test_partition.py`

Forbes' rule: the fraction of energy imbalance (`ΔE`) that goes to fat vs. lean depends on current fat mass. Higher fat → more of a deficit comes from fat, less from lean.

```
forbes_p(F) = 1 - 1 / (1 + 10.4*F/L_reference)
```

Standard form when F is in kg: `p = F / (F + C)` where C ≈ 10.4 kg for adult males. We expose a simple form and let the test pin the population-default behavior.

The protein-protection modifier shifts `p` toward fat-loss preservation of lean when protein intake is adequate (>1.6 g/kg body weight) and we are in deficit:

```
if deficit and protein_g_per_kg >= 1.6:  p_adjusted = p * (1 + protein_protection)  (capped at 1.0)
else: p_adjusted = p
```

`protein_protection` is a personalized parameter (default 0.5 at Phase 1).

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_partition.py`:

```python
import pytest

from body_sim import partition


def test_forbes_p_higher_at_higher_fat():
    p_lean = partition.forbes_p(fat_mass_kg=10)
    p_fat = partition.forbes_p(fat_mass_kg=30)
    assert p_fat > p_lean


def test_forbes_p_in_unit_interval():
    for F in (5, 15, 25, 40):
        p = partition.forbes_p(fat_mass_kg=F)
        assert 0 < p < 1


def test_protein_protection_only_in_deficit():
    # Surplus: protein doesn't change p
    p_base = partition.forbes_p(fat_mass_kg=20)
    p_adj_surplus = partition.adjusted_p(
        fat_mass_kg=20, protein_g=120, weight_kg=80, delta_e_kcal=500
    )
    assert p_adj_surplus == pytest.approx(p_base)


def test_protein_protection_increases_p_in_deficit():
    # Deficit + adequate protein: p shifts toward fat-loss preservation of lean
    p_base = partition.forbes_p(fat_mass_kg=20)
    p_adj_deficit = partition.adjusted_p(
        fat_mass_kg=20, protein_g=150, weight_kg=80, delta_e_kcal=-500  # 1.875 g/kg
    )
    assert p_adj_deficit > p_base


def test_protein_protection_no_effect_below_threshold():
    # Deficit + low protein: no protection
    p_base = partition.forbes_p(fat_mass_kg=20)
    p_adj = partition.adjusted_p(
        fat_mass_kg=20, protein_g=60, weight_kg=80, delta_e_kcal=-500  # 0.75 g/kg
    )
    assert p_adj == pytest.approx(p_base)


def test_protein_protection_capped_at_one():
    # Even with massive protein, p doesn't exceed 1.0
    p_adj = partition.adjusted_p(
        fat_mass_kg=40, protein_g=300, weight_kg=80, delta_e_kcal=-1000
    )
    assert p_adj <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_partition.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/partition.py`**

```python
"""Forbes partition fraction and protein-protection modifier.

Forbes 1987 + Hall 2008. The fraction `p` of energy imbalance that flows
into/out of fat mass (vs lean mass) is a monotonic function of current fat mass.
The protein-protection modifier increases lean-mass preservation during caloric
deficit when protein intake is adequate.
"""

from body_sim.config import DEFAULT_PARAMETERS

FORBES_C = 10.4  # kg, calibrated for adult population
PROTEIN_PROTECTION_THRESHOLD_G_PER_KG = 1.6


def forbes_p(fat_mass_kg: float) -> float:
    """Forbes partition fraction: share of ΔE that goes to/from fat mass.

    Higher fat mass → larger p (more of imbalance moves fat, less moves lean).
    Returned value is in (0, 1).
    """
    return fat_mass_kg / (fat_mass_kg + FORBES_C)


def adjusted_p(
    fat_mass_kg: float,
    protein_g: float,
    weight_kg: float,
    delta_e_kcal: float,
    protein_protection: float | None = None,
) -> float:
    """Forbes p with protein-protection modifier applied in deficit.

    Args:
        fat_mass_kg: current fat mass
        protein_g: today's protein intake in grams
        weight_kg: current total body weight
        delta_e_kcal: today's energy imbalance (negative = deficit)
        protein_protection: optional override of the personalized parameter

    Returns:
        Adjusted p, capped at [0, 1].
    """
    if protein_protection is None:
        protein_protection = DEFAULT_PARAMETERS["protein_protection"]
    p = forbes_p(fat_mass_kg)
    if delta_e_kcal >= 0:
        return p  # surplus: no protection effect
    protein_per_kg = protein_g / weight_kg if weight_kg > 0 else 0.0
    if protein_per_kg < PROTEIN_PROTECTION_THRESHOLD_G_PER_KG:
        return p
    return min(1.0, p * (1.0 + protein_protection))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_partition.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/partition.py tests/body_sim/test_partition.py
git commit -m "feat(body_sim): Forbes partition + protein-protection modifier"
```

---

## Task 9: Adaptive thermogenesis

**Files:**
- Create: `body_sim/adaptation.py`
- Test: `tests/body_sim/test_adaptation.py`

Adaptive thermogenesis is the "your body fights back" term: prolonged deficit lowers RMR beyond what the change in body composition alone would predict; prolonged surplus raises it. We model it as a slow-moving multiplicative scalar that follows recent energy balance:

```
adapt_{t+1} = adapt_t + tau * (delta_e_recent - 0)
adapt is clipped to [-0.2, +0.2] (i.e., up to 20% reduction or increase)
energy_balance_kcal = adapt * RMR (this is the term added to expenditure)
```

Where `delta_e_recent` is the trailing 7-day rolling average of `ΔE / RMR`, and `tau` is a small constant (~0.02/day) so the adaptation half-life is on the order of weeks.

This is a population-default approximation. The spec acknowledges Phase 1 may show residual drift here that motivates refinement.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_adaptation.py`:

```python
import numpy as np
import pytest

from body_sim import adaptation


def test_no_adaptation_at_zero_balance():
    state = adaptation.AdaptiveThermogenesisState()
    # Maintenance: 7 days of zero ΔE
    for _ in range(7):
        state = adaptation.update(state, delta_e_kcal=0, rmr_kcal=1700)
    assert state.adapt == pytest.approx(0.0, abs=0.005)


def test_adapt_drops_during_deficit():
    state = adaptation.AdaptiveThermogenesisState()
    for _ in range(30):
        state = adaptation.update(state, delta_e_kcal=-500, rmr_kcal=1700)
    assert state.adapt < -0.01  # at least 1% drop


def test_adapt_rises_during_surplus():
    state = adaptation.AdaptiveThermogenesisState()
    for _ in range(30):
        state = adaptation.update(state, delta_e_kcal=500, rmr_kcal=1700)
    assert state.adapt > 0.01


def test_adapt_capped_at_bounds():
    state = adaptation.AdaptiveThermogenesisState()
    # Extreme prolonged deficit
    for _ in range(365):
        state = adaptation.update(state, delta_e_kcal=-1500, rmr_kcal=1700)
    assert state.adapt >= -adaptation.MAX_ADAPT


def test_kcal_term_scales_with_rmr():
    state = adaptation.AdaptiveThermogenesisState(adapt=-0.05)
    assert adaptation.kcal_term(state, rmr_kcal=2000) == pytest.approx(-100.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_adaptation.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/adaptation.py`**

```python
"""Adaptive thermogenesis as a slow-moving multiplicative scalar.

Model: a state variable `adapt` (dimensionless) moves toward the recent
trailing energy balance fraction (ΔE/RMR), and the kcal contribution to
expenditure is `adapt * RMR`. Deficit → adapt < 0 → expenditure drops below
what mass alone predicts.

The adaptation timescale is set by TAU; the cap by MAX_ADAPT.
"""

from dataclasses import dataclass


TAU = 0.02            # per-day responsiveness; half-life ~35 days
MAX_ADAPT = 0.20      # ±20% bound


@dataclass
class AdaptiveThermogenesisState:
    adapt: float = 0.0


def update(
    state: AdaptiveThermogenesisState, delta_e_kcal: float, rmr_kcal: float
) -> AdaptiveThermogenesisState:
    """One-day update of the adaptation state.

    Args:
        state: previous-day state
        delta_e_kcal: today's energy imbalance
        rmr_kcal: today's RMR (so we can normalize ΔE)

    Returns:
        New state with `adapt` updated.
    """
    target = delta_e_kcal / rmr_kcal if rmr_kcal > 0 else 0.0
    new_adapt = state.adapt + TAU * (target - state.adapt)
    new_adapt = max(-MAX_ADAPT, min(MAX_ADAPT, new_adapt))
    return AdaptiveThermogenesisState(adapt=new_adapt)


def kcal_term(state: AdaptiveThermogenesisState, rmr_kcal: float) -> float:
    """The kcal contribution to today's expenditure from adaptation."""
    return state.adapt * rmr_kcal
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_adaptation.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/adaptation.py tests/body_sim/test_adaptation.py
git commit -m "feat(body_sim): adaptive thermogenesis as slow-moving scalar"
```

---

## Task 10: One-day Hall model state update

**Files:**
- Create: `body_sim/model.py`
- Test: `tests/body_sim/test_model.py`

Composes Tasks 3-9. Defines the state vector and the single-day transition function. State is a dataclass for clarity; the update is a pure function.

State:
```
fat_mass_kg, lean_mass_kg, glycogen_g, adapt_state
```

Inputs (one day):
```
intake_kcal, protein_g, carb_g, fat_g, sodium_mg, ee_hr_keytel_kcal,
workout_kcal, vigorous_min (carried for future use), intake_logged, hr_coverage_pct
```

Parameters (from `config.DEFAULT_PARAMETERS` at Phase 1):
```
intake_bias, RMR_scale, activity_bias, protein_protection, water_noise_sd
```

Returns: new state + a dictionary of derived diagnostic quantities (predicted weight, partition fraction, TEF, etc.) for plotting.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_model.py`:

```python
import pytest

from body_sim import model
from body_sim.config import DEFAULT_PARAMETERS, DEFAULT_PROFILE


@pytest.fixture
def initial_state():
    return model.BodyState(
        fat_mass_kg=20.0,
        lean_mass_kg=60.0,
        glycogen_g=400.0,
    )


@pytest.fixture
def maintenance_inputs():
    # Roughly maintenance for an 80kg, 40yr male:
    # RMR ~ 1700, activity ~ 600, TEF ~ 200 → ~2500 kcal
    return {
        "intake_kcal": 2500.0,
        "protein_g": 120.0,
        "carb_g": 300.0,
        "fat_g": 75.0,
        "sodium_mg": 2300.0,
        "ee_hr_keytel_kcal": 600.0,
        "workout_kcal": 0.0,
        "vigorous_min": 0,
        "intake_logged": True,
        "hr_coverage_pct": 100.0,
    }


def test_state_predicted_weight_includes_water(initial_state):
    predicted = initial_state.predicted_weight_kg(sodium_mg=2300.0)
    # fat + lean + glycogen-water + sodium-water (at baseline = 0)
    assert predicted == pytest.approx(20 + 60 + 1.4, abs=0.05)


def test_one_day_step_returns_new_state(initial_state, maintenance_inputs):
    new_state, diagnostics = model.step(
        state=initial_state,
        inputs=maintenance_inputs,
        profile=DEFAULT_PROFILE,
        parameters=DEFAULT_PARAMETERS,
    )
    assert isinstance(new_state, model.BodyState)
    assert "expenditure_kcal" in diagnostics
    assert "tef_kcal" in diagnostics
    assert "delta_e_kcal" in diagnostics
    assert "partition_p" in diagnostics


def test_surplus_increases_total_mass(initial_state):
    # Big surplus: fat + lean should grow
    inputs = {
        "intake_kcal": 4000.0,
        "protein_g": 150.0,
        "carb_g": 500.0,
        "fat_g": 100.0,
        "sodium_mg": 2300.0,
        "ee_hr_keytel_kcal": 500.0,
        "workout_kcal": 0.0,
        "vigorous_min": 0,
        "intake_logged": True,
        "hr_coverage_pct": 100.0,
    }
    new_state, _ = model.step(
        state=initial_state, inputs=inputs, profile=DEFAULT_PROFILE, parameters=DEFAULT_PARAMETERS
    )
    initial_mass = initial_state.fat_mass_kg + initial_state.lean_mass_kg
    new_mass = new_state.fat_mass_kg + new_state.lean_mass_kg
    assert new_mass > initial_mass


def test_deficit_decreases_total_mass(initial_state):
    inputs = {
        "intake_kcal": 1500.0,
        "protein_g": 100.0,
        "carb_g": 150.0,
        "fat_g": 50.0,
        "sodium_mg": 2300.0,
        "ee_hr_keytel_kcal": 700.0,
        "workout_kcal": 0.0,
        "vigorous_min": 0,
        "intake_logged": True,
        "hr_coverage_pct": 100.0,
    }
    new_state, _ = model.step(
        state=initial_state, inputs=inputs, profile=DEFAULT_PROFILE, parameters=DEFAULT_PARAMETERS
    )
    initial_mass = initial_state.fat_mass_kg + initial_state.lean_mass_kg
    new_mass = new_state.fat_mass_kg + new_state.lean_mass_kg
    assert new_mass < initial_mass


def test_intake_bias_applied(initial_state, maintenance_inputs):
    # intake_bias < 1 means we trust the log less (assume actually ate more)
    params = {**DEFAULT_PARAMETERS, "intake_bias": 0.7}
    new_state, diag = model.step(
        state=initial_state, inputs=maintenance_inputs, profile=DEFAULT_PROFILE, parameters=params
    )
    # intake_bias=0.7 with intake=2500 effectively means model assumes true intake is 2500/0.7 = ~3571
    # That's a surplus; mass should grow
    assert diag["effective_intake_kcal"] == pytest.approx(2500.0 / 0.7, abs=1.0)


def test_activity_fallback_when_hr_coverage_low(initial_state):
    # Low HR coverage → don't use Keytel; use workout_kcal + steps-derived estimate
    inputs = {
        "intake_kcal": 2500.0,
        "protein_g": 120.0,
        "carb_g": 300.0,
        "fat_g": 75.0,
        "sodium_mg": 2300.0,
        "ee_hr_keytel_kcal": 0.0,            # no HR data
        "workout_kcal": 200.0,
        "vigorous_min": 30,
        "intake_logged": True,
        "hr_coverage_pct": 10.0,             # below threshold
        "steps": 8000,                       # fallback signal
    }
    new_state, diag = model.step(
        state=initial_state, inputs=inputs, profile=DEFAULT_PROFILE, parameters=DEFAULT_PARAMETERS
    )
    assert diag["activity_source"] == "fallback"
    assert diag["activity_kcal"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_model.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/model.py`**

```python
"""One-day state update for the extended Hall energy-balance model.

Composes Keytel HR-to-kcal, Mifflin RMR, TEF, Forbes partition, glycogen-water,
sodium-water, and adaptive thermogenesis into a single per-day step function.

This is the kernel of the simulator. Both forward simulation and validation
call `step()` repeatedly with daily inputs.
"""

from dataclasses import dataclass, field, replace

from body_sim import adaptation, glycogen, partition, rmr, sodium, tef
from body_sim.config import (
    DEFAULT_PARAMETERS,
    KCAL_PER_KG_FAT,
    KCAL_PER_KG_LEAN,
    UserProfile,
)

HR_COVERAGE_THRESHOLD_PCT = 50.0
KCAL_PER_STEP = 0.04  # rough fallback when HR data is unavailable


@dataclass
class BodyState:
    fat_mass_kg: float
    lean_mass_kg: float
    glycogen_g: float = glycogen.INITIAL_GLYCOGEN_G
    adapt: adaptation.AdaptiveThermogenesisState = field(
        default_factory=adaptation.AdaptiveThermogenesisState
    )

    @property
    def total_mass_kg(self) -> float:
        return self.fat_mass_kg + self.lean_mass_kg

    def predicted_weight_kg(self, sodium_mg: float) -> float:
        """Predicted scale reading: total mass + glycogen water + sodium water."""
        return (
            self.fat_mass_kg
            + self.lean_mass_kg
            + glycogen.water_kg_from_glycogen(self.glycogen_g)
            + sodium.water_kg(sodium_mg)
        )

    def body_fat_pct(self) -> float:
        return 100.0 * self.fat_mass_kg / max(0.001, self.total_mass_kg)


def _activity_kcal(inputs: dict, parameters: dict) -> tuple[float, str]:
    """Pick HR-Keytel when coverage is high; fall back to workout + steps."""
    hr_coverage = inputs.get("hr_coverage_pct", 0.0)
    if hr_coverage >= HR_COVERAGE_THRESHOLD_PCT:
        kcal = inputs["ee_hr_keytel_kcal"] * parameters["activity_bias"]
        return kcal, "keytel"
    workout = inputs.get("workout_kcal", 0.0)
    steps = inputs.get("steps", 0) or 0
    kcal = (workout + steps * KCAL_PER_STEP) * parameters["activity_bias"]
    return kcal, "fallback"


def step(
    state: BodyState,
    inputs: dict,
    profile: UserProfile,
    parameters: dict | None = None,
) -> tuple[BodyState, dict]:
    """Advance the body state by one day.

    Args:
        state: previous-day state
        inputs: daily input dict (see model docstring for keys)
        profile: user profile (age, sex, height)
        parameters: model parameters; defaults to population values

    Returns:
        (new state, diagnostics dict with derived intermediates)
    """
    if parameters is None:
        parameters = DEFAULT_PARAMETERS

    effective_intake = inputs["intake_kcal"] / parameters["intake_bias"]

    rmr_kcal = rmr.mifflin_st_jeor(
        weight_kg=state.total_mass_kg,
        height_cm=profile["height_cm"],
        age=profile["age"],
        sex=profile["sex"],
    ) * parameters["RMR_scale"]

    activity_kcal, activity_source = _activity_kcal(inputs, parameters)

    tef_kcal = tef.tef_kcal(
        protein_g=inputs["protein_g"],
        carb_g=inputs["carb_g"],
        fat_g=inputs["fat_g"],
    )

    adapt_kcal = adaptation.kcal_term(state.adapt, rmr_kcal)

    expenditure = rmr_kcal + activity_kcal + tef_kcal + adapt_kcal
    delta_e = effective_intake - expenditure

    p = partition.adjusted_p(
        fat_mass_kg=state.fat_mass_kg,
        protein_g=inputs["protein_g"],
        weight_kg=state.total_mass_kg,
        delta_e_kcal=delta_e,
        protein_protection=parameters["protein_protection"],
    )

    delta_fat = p * delta_e / KCAL_PER_KG_FAT
    delta_lean = (1 - p) * delta_e / KCAL_PER_KG_LEAN

    new_glycogen = glycogen.update(state.glycogen_g, inputs["carb_g"])
    new_adapt = adaptation.update(state.adapt, delta_e_kcal=delta_e, rmr_kcal=rmr_kcal)

    new_state = BodyState(
        fat_mass_kg=max(2.0, state.fat_mass_kg + delta_fat),
        lean_mass_kg=max(20.0, state.lean_mass_kg + delta_lean),
        glycogen_g=new_glycogen,
        adapt=new_adapt,
    )

    diagnostics = {
        "effective_intake_kcal": effective_intake,
        "rmr_kcal": rmr_kcal,
        "activity_kcal": activity_kcal,
        "activity_source": activity_source,
        "tef_kcal": tef_kcal,
        "adapt_kcal": adapt_kcal,
        "expenditure_kcal": expenditure,
        "delta_e_kcal": delta_e,
        "partition_p": p,
        "delta_fat_kg": delta_fat,
        "delta_lean_kg": delta_lean,
        "predicted_weight_kg": new_state.predicted_weight_kg(inputs["sodium_mg"]),
    }
    return new_state, diagnostics
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_model.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/model.py tests/body_sim/test_model.py
git commit -m "feat(body_sim): one-day Hall energy-balance state update"
```

---

## Task 11: Data pipeline — food rollup

**Files:**
- Create: `body_sim/pipeline.py` (initial — food-only)
- Test: `tests/body_sim/test_pipeline_food.py`

`pipeline.py` will grow incrementally across Tasks 11-15. We start with just the food rollup: query `food_entries`, group by date, return a DataFrame with intake totals + meal-type coverage.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_pipeline_food.py`:

```python
import datetime

import pandas as pd
import pytest

from body_sim import pipeline
from foodlog.db.models import FoodEntry


def _make_food_entry(
    db, dt: datetime.datetime, meal_type: str, kcal: float, p=10.0, c=20.0, f=5.0, na=300.0
):
    entry = FoodEntry(
        meal_type=meal_type,
        food_name="test food",
        quantity=1.0,
        unit="serving",
        calories=kcal,
        protein_g=p,
        carbs_g=c,
        fat_g=f,
        sodium_mg=na,
        source="manual",
        raw_input="test",
        logged_at=dt,
    )
    db.add(entry)
    return entry


def test_food_rollup_empty(session):
    df = pipeline.rollup_food(
        session,
        start=datetime.date(2026, 5, 1),
        end=datetime.date(2026, 5, 3),
    )
    # Three rows (one per day in [start, end]), all NaN intake
    assert len(df) == 3
    assert df["intake_kcal"].isna().all()
    assert (df["intake_coverage"] == 0.0).all()


def test_food_rollup_single_meal(session):
    d = datetime.date(2026, 5, 1)
    dt = datetime.datetime(2026, 5, 1, 12, 30)
    _make_food_entry(session, dt, "lunch", 500.0)
    session.commit()
    df = pipeline.rollup_food(session, start=d, end=d)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["intake_kcal"] == pytest.approx(500.0)
    assert row["intake_coverage"] == pytest.approx(1.0 / 3.0)
    assert row["intake_logged"] is False  # below 0.67 threshold


def test_food_rollup_full_coverage(session):
    d = datetime.date(2026, 5, 1)
    for hour, meal in [(8, "breakfast"), (12, "lunch"), (19, "dinner")]:
        dt = datetime.datetime(2026, 5, 1, hour, 0)
        _make_food_entry(session, dt, meal, 600.0)
    session.commit()
    df = pipeline.rollup_food(session, start=d, end=d)
    row = df.iloc[0]
    assert row["intake_kcal"] == pytest.approx(1800.0)
    assert row["intake_coverage"] == pytest.approx(1.0)
    assert row["intake_logged"] is True


def test_food_rollup_snacks_ignored_for_coverage(session):
    d = datetime.date(2026, 5, 1)
    # Lunch + 5 snacks: coverage should still be 1/3, not 2/3
    _make_food_entry(session, datetime.datetime(2026, 5, 1, 12, 0), "lunch", 500.0)
    for h in range(13, 18):
        _make_food_entry(session, datetime.datetime(2026, 5, 1, h, 0), "snack", 100.0)
    session.commit()
    df = pipeline.rollup_food(session, start=d, end=d)
    row = df.iloc[0]
    assert row["intake_coverage"] == pytest.approx(1.0 / 3.0)


def test_food_rollup_aggregates_macros(session):
    d = datetime.date(2026, 5, 1)
    _make_food_entry(
        session, datetime.datetime(2026, 5, 1, 8, 0), "breakfast", 500.0,
        p=30, c=50, f=15, na=400,
    )
    _make_food_entry(
        session, datetime.datetime(2026, 5, 1, 12, 0), "lunch", 700.0,
        p=40, c=80, f=20, na=600,
    )
    session.commit()
    df = pipeline.rollup_food(session, start=d, end=d)
    row = df.iloc[0]
    assert row["protein_g"] == pytest.approx(70.0)
    assert row["carb_g"] == pytest.approx(130.0)
    assert row["fat_g"] == pytest.approx(35.0)
    assert row["sodium_mg"] == pytest.approx(1000.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_pipeline_food.py -v
```

Expected: `ModuleNotFoundError: No module named 'body_sim.pipeline'`

- [ ] **Step 3: Implement `body_sim/pipeline.py` (food-only first pass)**

```python
"""SQLite-to-pandas daily-rollup pipeline for body_sim.

Single entry point: `build_daily_rollup(session, start, end)`. Internally
composed of per-source helpers (rollup_food, rollup_activity, etc.) so each is
independently testable.

All helpers return a DataFrame indexed by date with one row per day in
[start, end] inclusive — missing days are present with NaN/zero per the
missingness conventions in the spec.
"""

import datetime

import numpy as np
import pandas as pd
from sqlalchemy import cast, func
from sqlalchemy.orm import Session
from sqlalchemy.types import Date

from foodlog.db.models import FoodEntry


def _date_index(start: datetime.date, end: datetime.date) -> pd.DatetimeIndex:
    """Daily index covering [start, end] inclusive."""
    return pd.date_range(start=start, end=end, freq="D", name="date")


def rollup_food(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    """Aggregate `food_entries` to one row per day with intake totals + coverage."""
    rows = (
        session.query(
            cast(FoodEntry.logged_at, Date).label("d"),
            FoodEntry.meal_type,
            func.sum(FoodEntry.calories).label("kcal"),
            func.sum(FoodEntry.protein_g).label("p"),
            func.sum(FoodEntry.carbs_g).label("c"),
            func.sum(FoodEntry.fat_g).label("f"),
            func.sum(FoodEntry.sodium_mg).label("na"),
            func.count().label("n"),
        )
        .filter(
            cast(FoodEntry.logged_at, Date) >= start,
            cast(FoodEntry.logged_at, Date) <= end,
        )
        .group_by("d", FoodEntry.meal_type)
        .all()
    )

    # Build per-day aggregates
    per_day: dict[datetime.date, dict] = {}
    for r in rows:
        d = r.d if isinstance(r.d, datetime.date) else datetime.date.fromisoformat(str(r.d))
        cell = per_day.setdefault(
            d,
            {
                "intake_kcal": 0.0,
                "protein_g": 0.0,
                "carb_g": 0.0,
                "fat_g": 0.0,
                "sodium_mg": 0.0,
                "meal_types_logged": set(),
                "n_entries": 0,
            },
        )
        cell["intake_kcal"] += r.kcal or 0
        cell["protein_g"] += r.p or 0
        cell["carb_g"] += r.c or 0
        cell["fat_g"] += r.f or 0
        cell["sodium_mg"] += r.na or 0
        cell["meal_types_logged"].add(r.meal_type)
        cell["n_entries"] += r.n

    # Materialize one row per day in the requested range
    idx = _date_index(start, end)
    records = []
    for ts in idx:
        d = ts.date()
        if d in per_day:
            cell = per_day[d]
            main_meals = {"breakfast", "lunch", "dinner"} & cell["meal_types_logged"]
            coverage = len(main_meals) / 3.0
            records.append(
                {
                    "intake_kcal": cell["intake_kcal"],
                    "protein_g": cell["protein_g"],
                    "carb_g": cell["carb_g"],
                    "fat_g": cell["fat_g"],
                    "sodium_mg": cell["sodium_mg"],
                    "meal_types_logged": frozenset(cell["meal_types_logged"]),
                    "intake_coverage": coverage,
                    "intake_logged": coverage >= 0.67,
                }
            )
        else:
            records.append(
                {
                    "intake_kcal": np.nan,
                    "protein_g": np.nan,
                    "carb_g": np.nan,
                    "fat_g": np.nan,
                    "sodium_mg": np.nan,
                    "meal_types_logged": frozenset(),
                    "intake_coverage": 0.0,
                    "intake_logged": False,
                }
            )
    return pd.DataFrame(records, index=idx)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_pipeline_food.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/pipeline.py tests/body_sim/test_pipeline_food.py
git commit -m "feat(body_sim): pipeline food rollup with meal-type coverage"
```

---

## Task 12: Data pipeline — activity rollup (steps + HR-Keytel)

**Files:**
- Modify: `body_sim/pipeline.py` (add `rollup_activity`)
- Test: `tests/body_sim/test_pipeline_activity.py`

Adds `rollup_activity(session, start, end, weight_kg, age, sex)`. Pulls `daily_activity`, `interval_heart_rate`, `interval_azm` and produces per-day columns: `steps`, `active_kcal_fitbit`, `ee_hr_keytel_kcal`, `hr_coverage_pct`, `vigorous_min`, `cardio_min`.

The Keytel integration needs the user's weight on each day. For Phase 1 we use the most recent observed weight or fall back to the user-profile estimate (computed in Task 14 where we assemble the full DataFrame). For per-day testing here, weight_kg is passed in.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_pipeline_activity.py`:

```python
import datetime

import numpy as np
import pandas as pd
import pytest

from body_sim import pipeline
from foodlog.db.models import DailyActivity, IntervalAzm, IntervalHeartRate


def _add_daily_activity(db, d: datetime.date, steps: int, active_kcal: float):
    db.add(
        DailyActivity(
            date=d,
            steps=steps,
            active_calories_kcal=active_kcal,
            source="fitbit",
            external_id=f"da-{d}",
        )
    )


def _add_hr_interval(db, dt: datetime.datetime, bpm: int):
    db.add(
        IntervalHeartRate(
            start_at=dt,
            bpm_avg=bpm,
            bpm_min=bpm - 5,
            bpm_max=bpm + 5,
            source="fitbit",
        )
    )


def _add_azm(db, dt: datetime.datetime, fat_burn: int = 0, cardio: int = 0, peak: int = 0):
    db.add(
        IntervalAzm(
            start_at=dt,
            fat_burn_min=fat_burn,
            cardio_min=cardio,
            peak_min=peak,
            source="fitbit",
        )
    )


def test_activity_rollup_empty(session):
    df = pipeline.rollup_activity(
        session,
        start=datetime.date(2026, 5, 1),
        end=datetime.date(2026, 5, 2),
        weight_kg=80.0,
        age=40,
        sex="male",
    )
    assert len(df) == 2
    assert df["steps"].isna().all()
    assert (df["vigorous_min"] == 0).all()
    assert (df["hr_coverage_pct"] == 0.0).all()


def test_activity_rollup_daily_only(session):
    d = datetime.date(2026, 5, 1)
    _add_daily_activity(session, d, steps=10000, active_kcal=400.0)
    session.commit()
    df = pipeline.rollup_activity(
        session, start=d, end=d, weight_kg=80.0, age=40, sex="male"
    )
    row = df.iloc[0]
    assert row["steps"] == 10000
    assert row["active_kcal_fitbit"] == pytest.approx(400.0)


def test_activity_rollup_with_full_hr_coverage(session):
    d = datetime.date(2026, 5, 1)
    _add_daily_activity(session, d, steps=8000, active_kcal=300.0)
    # 1440 minutes of HR at 80 bpm
    for m in range(1440):
        dt = datetime.datetime.combine(d, datetime.time()) + datetime.timedelta(minutes=m)
        _add_hr_interval(session, dt, bpm=80)
    session.commit()
    df = pipeline.rollup_activity(
        session, start=d, end=d, weight_kg=80.0, age=40, sex="male"
    )
    row = df.iloc[0]
    assert row["hr_coverage_pct"] == pytest.approx(100.0, abs=0.1)
    assert row["ee_hr_keytel_kcal"] > 1000  # plausible 24h expenditure at 80 bpm avg


def test_activity_rollup_aggregates_azm(session):
    d = datetime.date(2026, 5, 1)
    _add_azm(session, datetime.datetime(2026, 5, 1, 8, 0), fat_burn=10)
    _add_azm(session, datetime.datetime(2026, 5, 1, 10, 0), cardio=15)
    _add_azm(session, datetime.datetime(2026, 5, 1, 18, 0), peak=5, cardio=5)
    session.commit()
    df = pipeline.rollup_activity(
        session, start=d, end=d, weight_kg=80.0, age=40, sex="male"
    )
    row = df.iloc[0]
    assert row["cardio_min"] == 20
    assert row["vigorous_min"] == 5  # peak only


def test_activity_rollup_partial_hr_coverage(session):
    d = datetime.date(2026, 5, 1)
    # Only 12 hours of HR data
    for m in range(720):
        dt = datetime.datetime.combine(d, datetime.time()) + datetime.timedelta(minutes=m)
        _add_hr_interval(session, dt, bpm=80)
    session.commit()
    df = pipeline.rollup_activity(
        session, start=d, end=d, weight_kg=80.0, age=40, sex="male"
    )
    row = df.iloc[0]
    assert row["hr_coverage_pct"] == pytest.approx(50.0, abs=0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_pipeline_activity.py -v
```

Expected: `AttributeError: module 'body_sim.pipeline' has no attribute 'rollup_activity'`

- [ ] **Step 3: Implement `rollup_activity` in `body_sim/pipeline.py`**

Add these imports at the top of `body_sim/pipeline.py`:

```python
from foodlog.db.models import DailyActivity, IntervalAzm, IntervalHeartRate

from body_sim import keytel
```

Then append:

```python
def rollup_activity(
    session: Session,
    start: datetime.date,
    end: datetime.date,
    weight_kg: float,
    age: int,
    sex: str,
) -> pd.DataFrame:
    """Aggregate activity sources to one row per day.

    Columns: steps, active_kcal_fitbit, ee_hr_keytel_kcal, hr_coverage_pct,
    vigorous_min, cardio_min.
    """
    idx = _date_index(start, end)
    records = {ts.date(): _empty_activity_row() for ts in idx}

    # Daily activity (Fitbit rollup)
    da_rows = (
        session.query(DailyActivity)
        .filter(DailyActivity.date >= start, DailyActivity.date <= end)
        .all()
    )
    for r in da_rows:
        cell = records[r.date]
        cell["steps"] = r.steps
        cell["active_kcal_fitbit"] = r.active_calories_kcal

    # AZM intervals
    azm_rows = (
        session.query(IntervalAzm)
        .filter(
            IntervalAzm.start_at >= datetime.datetime.combine(start, datetime.time()),
            IntervalAzm.start_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .all()
    )
    for r in azm_rows:
        d = r.start_at.date()
        cell = records[d]
        cell["cardio_min"] += r.cardio_min or 0
        cell["vigorous_min"] += r.peak_min or 0  # peak = vigorous in our convention

    # HR intervals → daily Keytel + coverage
    hr_rows = (
        session.query(IntervalHeartRate)
        .filter(
            IntervalHeartRate.start_at >= datetime.datetime.combine(start, datetime.time()),
            IntervalHeartRate.start_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .all()
    )
    per_day_hr: dict[datetime.date, list[int]] = {ts.date(): [] for ts in idx}
    for r in hr_rows:
        per_day_hr[r.start_at.date()].append(r.bpm_avg)

    for d, bpms in per_day_hr.items():
        if not bpms:
            continue
        arr = np.full(1440, np.nan)
        arr[: len(bpms)] = bpms
        cell = records[d]
        cell["ee_hr_keytel_kcal"] = keytel.daily_integral(
            arr, weight_kg=weight_kg, age=age, sex=sex
        )
        cell["hr_coverage_pct"] = keytel.coverage_pct(arr)

    df = pd.DataFrame([records[ts.date()] for ts in idx], index=idx)
    return df


def _empty_activity_row() -> dict:
    return {
        "steps": np.nan,
        "active_kcal_fitbit": np.nan,
        "ee_hr_keytel_kcal": np.nan,
        "hr_coverage_pct": 0.0,
        "vigorous_min": 0,
        "cardio_min": 0,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_pipeline_activity.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/pipeline.py tests/body_sim/test_pipeline_activity.py
git commit -m "feat(body_sim): pipeline activity rollup (steps, HR-Keytel, AZM)"
```

---

## Task 13: Data pipeline — body composition, RHR, sleep, workouts

**Files:**
- Modify: `body_sim/pipeline.py` (add `rollup_body_comp`, `rollup_rhr`, `rollup_sleep`, `rollup_workouts`)
- Test: `tests/body_sim/test_pipeline_other.py`

Four small helpers, each returning a DataFrame with the same date index.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_pipeline_other.py`:

```python
import datetime

import numpy as np
import pytest

from body_sim import pipeline
from foodlog.db.models import BodyComposition, RestingHeartRate, SleepSession, Workout


def test_body_comp_rollup_empty(session):
    df = pipeline.rollup_body_comp(
        session, start=datetime.date(2026, 5, 1), end=datetime.date(2026, 5, 2)
    )
    assert df["weight_kg"].isna().all()
    assert df["bf_pct"].isna().all()
    assert (df["n_weighins"] == 0).all()


def test_body_comp_rollup_single_reading(session):
    d = datetime.date(2026, 5, 1)
    session.add(BodyComposition(
        external_id="bc-1",
        measured_at=datetime.datetime(2026, 5, 1, 7, 30),
        source="withings",
        weight_kg=80.5,
        body_fat_pct=22.0,
    ))
    session.commit()
    df = pipeline.rollup_body_comp(session, start=d, end=d)
    row = df.iloc[0]
    assert row["weight_kg"] == pytest.approx(80.5)
    assert row["bf_pct"] == pytest.approx(22.0)
    assert row["n_weighins"] == 1


def test_body_comp_rollup_median_of_multiple(session):
    d = datetime.date(2026, 5, 1)
    for i, (w, bf) in enumerate([(80.0, 22.0), (80.5, 22.5), (81.0, 23.0)]):
        session.add(BodyComposition(
            external_id=f"bc-{i}",
            measured_at=datetime.datetime(2026, 5, 1, 7 + i, 0),
            source="withings",
            weight_kg=w,
            body_fat_pct=bf,
        ))
    session.commit()
    df = pipeline.rollup_body_comp(session, start=d, end=d)
    row = df.iloc[0]
    assert row["weight_kg"] == pytest.approx(80.5)  # median
    assert row["bf_pct"] == pytest.approx(22.5)
    assert row["n_weighins"] == 3


def test_rhr_rollup_forward_fills_three_days(session):
    # RHR on day 1, missing days 2-4. Days 2-3-4 forward-fill; day 5 NaN.
    session.add(RestingHeartRate(
        external_id="rhr-1",
        measured_at=datetime.datetime(2026, 5, 1, 0, 0),
        source="fitbit",
        bpm=58,
    ))
    session.commit()
    df = pipeline.rollup_rhr(
        session, start=datetime.date(2026, 5, 1), end=datetime.date(2026, 5, 6)
    )
    assert df.iloc[0]["rhr_bpm"] == 58
    assert df.iloc[1]["rhr_bpm"] == 58  # ffill day 1
    assert df.iloc[2]["rhr_bpm"] == 58  # ffill day 2
    assert df.iloc[3]["rhr_bpm"] == 58  # ffill day 3
    assert np.isnan(df.iloc[4]["rhr_bpm"])  # past 3-day ffill, NaN
    assert np.isnan(df.iloc[5]["rhr_bpm"])


def test_sleep_rollup_prev_night(session):
    # Sleep ending early morning of 2026-05-02 → assigned to 2026-05-02 row
    session.add(SleepSession(
        external_id="sleep-1",
        start_at=datetime.datetime(2026, 5, 1, 23, 30),
        end_at=datetime.datetime(2026, 5, 2, 7, 0),
        duration_min=450,
        source="fitbit",
    ))
    session.commit()
    df = pipeline.rollup_sleep(
        session, start=datetime.date(2026, 5, 1), end=datetime.date(2026, 5, 2)
    )
    assert np.isnan(df.iloc[0]["sleep_total_h_prev_night"])  # no row for day 1
    assert df.iloc[1]["sleep_total_h_prev_night"] == pytest.approx(7.5)


def test_workouts_rollup_zero_when_none(session):
    df = pipeline.rollup_workouts(
        session, start=datetime.date(2026, 5, 1), end=datetime.date(2026, 5, 1)
    )
    assert df.iloc[0]["workout_kcal"] == 0
    assert df.iloc[0]["workout_min"] == 0


def test_workouts_rollup_aggregates_by_start_date(session):
    d = datetime.date(2026, 5, 1)
    session.add(Workout(
        external_id="w-1",
        start_at=datetime.datetime(2026, 5, 1, 6, 0),
        end_at=datetime.datetime(2026, 5, 1, 7, 0),
        activity_type="run",
        duration_min=60,
        calories_kcal=500.0,
        source="fitbit",
    ))
    session.add(Workout(
        external_id="w-2",
        start_at=datetime.datetime(2026, 5, 1, 18, 0),
        end_at=datetime.datetime(2026, 5, 1, 18, 30),
        activity_type="weights",
        duration_min=30,
        calories_kcal=150.0,
        source="manual",
    ))
    session.commit()
    df = pipeline.rollup_workouts(session, start=d, end=d)
    assert df.iloc[0]["workout_kcal"] == pytest.approx(650.0)
    assert df.iloc[0]["workout_min"] == 90
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_pipeline_other.py -v
```

Expected: `AttributeError` on missing functions.

- [ ] **Step 3: Implement the four helpers in `body_sim/pipeline.py`**

Add imports:

```python
from foodlog.db.models import BodyComposition, RestingHeartRate, SleepSession, Workout
```

Then append:

```python
def rollup_body_comp(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    rows = (
        session.query(BodyComposition)
        .filter(
            BodyComposition.measured_at >= datetime.datetime.combine(start, datetime.time()),
            BodyComposition.measured_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .all()
    )
    per_day: dict[datetime.date, list[BodyComposition]] = {}
    for r in rows:
        per_day.setdefault(r.measured_at.date(), []).append(r)

    idx = _date_index(start, end)
    records = []
    for ts in idx:
        d = ts.date()
        rs = per_day.get(d, [])
        if rs:
            weights = [r.weight_kg for r in rs if r.weight_kg is not None]
            bfs = [r.body_fat_pct for r in rs if r.body_fat_pct is not None]
            records.append(
                {
                    "weight_kg": float(np.median(weights)) if weights else np.nan,
                    "bf_pct": float(np.median(bfs)) if bfs else np.nan,
                    "n_weighins": len(rs),
                }
            )
        else:
            records.append({"weight_kg": np.nan, "bf_pct": np.nan, "n_weighins": 0})
    return pd.DataFrame(records, index=idx)


def rollup_rhr(
    session: Session, start: datetime.date, end: datetime.date, ffill_days: int = 3
) -> pd.DataFrame:
    # Pull a small window before start so we can ffill into the first days of the range
    fetch_start = start - datetime.timedelta(days=ffill_days)
    rows = (
        session.query(RestingHeartRate)
        .filter(
            RestingHeartRate.measured_at >= datetime.datetime.combine(fetch_start, datetime.time()),
            RestingHeartRate.measured_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .order_by(RestingHeartRate.measured_at)
        .all()
    )
    by_date = {r.measured_at.date(): r.bpm for r in rows}

    idx = _date_index(start, end)
    records = []
    for ts in idx:
        d = ts.date()
        # Look back up to ffill_days for a recent value
        value = np.nan
        for back in range(ffill_days + 1):
            cand = d - datetime.timedelta(days=back)
            if cand in by_date:
                value = float(by_date[cand])
                break
        records.append({"rhr_bpm": value})
    return pd.DataFrame(records, index=idx)


def rollup_sleep(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    # Sleep session ending on day D before noon counts as 'prev night sleep for D'
    fetch_start = start - datetime.timedelta(days=1)
    rows = (
        session.query(SleepSession)
        .filter(
            SleepSession.end_at >= datetime.datetime.combine(fetch_start, datetime.time()),
            SleepSession.end_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time(12, 0)
            ),
        )
        .all()
    )
    per_day: dict[datetime.date, float] = {}
    for r in rows:
        end_dt = r.end_at
        if end_dt.hour < 12:
            d = end_dt.date()
        else:
            continue  # naps / late-day sleep; not 'prev night'
        per_day[d] = per_day.get(d, 0.0) + r.duration_min / 60.0

    idx = _date_index(start, end)
    records = [
        {"sleep_total_h_prev_night": per_day.get(ts.date(), np.nan)} for ts in idx
    ]
    return pd.DataFrame(records, index=idx)


def rollup_workouts(
    session: Session, start: datetime.date, end: datetime.date
) -> pd.DataFrame:
    rows = (
        session.query(Workout)
        .filter(
            Workout.start_at >= datetime.datetime.combine(start, datetime.time()),
            Workout.start_at < datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time()
            ),
        )
        .all()
    )
    per_day: dict[datetime.date, dict] = {}
    for r in rows:
        cell = per_day.setdefault(r.start_at.date(), {"workout_kcal": 0.0, "workout_min": 0})
        cell["workout_kcal"] += r.calories_kcal or 0
        cell["workout_min"] += r.duration_min or 0

    idx = _date_index(start, end)
    records = [
        per_day.get(ts.date(), {"workout_kcal": 0.0, "workout_min": 0}) for ts in idx
    ]
    return pd.DataFrame(records, index=idx)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_pipeline_other.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/pipeline.py tests/body_sim/test_pipeline_other.py
git commit -m "feat(body_sim): pipeline body-comp, RHR, sleep, workout rollups"
```

---

## Task 14: Data pipeline — assemble the full daily-rollup DataFrame

**Files:**
- Modify: `body_sim/pipeline.py` (add `build_daily_rollup`)
- Test: `tests/body_sim/test_pipeline_assembly.py`

The public entry point. Calls each helper and joins on the date index.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_pipeline_assembly.py`:

```python
import datetime

import pytest

from body_sim import pipeline
from foodlog.db.models import BodyComposition, DailyActivity, FoodEntry


def test_build_daily_rollup_columns_present(session):
    df = pipeline.build_daily_rollup(
        session,
        start=datetime.date(2026, 5, 1),
        end=datetime.date(2026, 5, 3),
        weight_kg_fallback=80.0,
        age=40,
        sex="male",
    )
    expected_cols = {
        "intake_kcal", "protein_g", "carb_g", "fat_g", "sodium_mg",
        "meal_types_logged", "intake_coverage", "intake_logged",
        "steps", "active_kcal_fitbit", "ee_hr_keytel_kcal",
        "hr_coverage_pct", "vigorous_min", "cardio_min",
        "rhr_bpm",
        "workout_kcal", "workout_min",
        "sleep_total_h_prev_night",
        "weight_kg", "bf_pct", "n_weighins",
    }
    assert expected_cols.issubset(df.columns)
    assert len(df) == 3


def test_build_daily_rollup_uses_observed_weight_for_keytel(session):
    # Add a weigh-in on day 1; HR-Keytel on day 2 should use that weight
    d1 = datetime.date(2026, 5, 1)
    d2 = datetime.date(2026, 5, 2)
    session.add(BodyComposition(
        external_id="bc-1",
        measured_at=datetime.datetime(2026, 5, 1, 7, 30),
        source="withings",
        weight_kg=85.0,
        body_fat_pct=22.0,
    ))
    session.commit()

    df = pipeline.build_daily_rollup(
        session, start=d1, end=d2,
        weight_kg_fallback=80.0, age=40, sex="male",
    )
    # We can't directly verify Keytel from here without HR data, but we can
    # confirm a 'reference_weight_kg' column is exposed for diagnostic plotting
    assert "reference_weight_kg" in df.columns
    assert df.loc[df.index[1], "reference_weight_kg"] == pytest.approx(85.0)


def test_build_daily_rollup_fallback_weight_used_when_no_observation(session):
    df = pipeline.build_daily_rollup(
        session,
        start=datetime.date(2026, 5, 1),
        end=datetime.date(2026, 5, 1),
        weight_kg_fallback=80.0, age=40, sex="male",
    )
    assert df.iloc[0]["reference_weight_kg"] == pytest.approx(80.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_pipeline_assembly.py -v
```

Expected: `AttributeError: module 'body_sim.pipeline' has no attribute 'build_daily_rollup'`

- [ ] **Step 3: Append `build_daily_rollup` to `body_sim/pipeline.py`**

```python
def build_daily_rollup(
    session: Session,
    start: datetime.date,
    end: datetime.date,
    weight_kg_fallback: float,
    age: int,
    sex: str,
) -> pd.DataFrame:
    """Build the canonical daily-rollup DataFrame for body_sim.

    Args:
        session: SQLAlchemy session against the foodlog DB
        start, end: inclusive date range
        weight_kg_fallback: weight to use for Keytel on days before any observed weigh-in
        age, sex: user profile

    Returns:
        DataFrame indexed by date, one row per day in [start, end].
    """
    food = rollup_food(session, start, end)
    bc = rollup_body_comp(session, start, end)
    rhr = rollup_rhr(session, start, end)
    sleep = rollup_sleep(session, start, end)
    workouts = rollup_workouts(session, start, end)

    # Reference weight per day: most recent observed weight up to and including that day,
    # or fallback if none yet observed.
    weight_series = bc["weight_kg"].ffill().fillna(weight_kg_fallback)
    activity = rollup_activity_with_per_day_weight(
        session, start, end, weight_series, age, sex
    )

    df = pd.concat([food, activity, bc, rhr, sleep, workouts], axis=1)
    df["reference_weight_kg"] = weight_series
    return df


def rollup_activity_with_per_day_weight(
    session: Session,
    start: datetime.date,
    end: datetime.date,
    weight_series: pd.Series,
    age: int,
    sex: str,
) -> pd.DataFrame:
    """Variant of rollup_activity that uses a per-day weight Series for Keytel.

    Calls rollup_activity day-by-day so the Keytel integral matches the
    reference weight on each day. Slightly wasteful in queries but trivial for
    Phase 1 data volumes.
    """
    frames = []
    for ts, weight in weight_series.items():
        d = ts.date()
        sub = rollup_activity(session, start=d, end=d, weight_kg=float(weight), age=age, sex=sex)
        frames.append(sub)
    return pd.concat(frames)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_pipeline_assembly.py -v
```

Expected: 3 passed

- [ ] **Step 5: Run the full test suite for body_sim to catch regressions**

```bash
pytest tests/body_sim/ -v
```

Expected: all tests in tasks 2-13 pass plus 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add body_sim/pipeline.py tests/body_sim/test_pipeline_assembly.py
git commit -m "feat(body_sim): assemble full daily-rollup DataFrame"
```

---

## Task 15: Forward-simulate scenarios with uncertainty bands

**Files:**
- Create: `body_sim/simulate.py`
- Test: `tests/body_sim/test_simulate.py`

`simulate_forward(initial_state, inputs_per_day, profile, parameter_samples)` runs the model forward for N days, once per parameter sample, and returns an `np.ndarray` of shape `(n_samples, n_days, n_quantities)` plus a metadata dict with column names.

For Phase 1, `parameter_samples` are drawn from the priors in `config.DEFAULT_PARAMETERS` (with small Gaussian noise reflecting prior uncertainty). At Phase 2 these will come from the PyMC posterior — same interface.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_simulate.py`:

```python
import numpy as np
import pytest

from body_sim import simulate
from body_sim.config import DEFAULT_PARAMETERS, DEFAULT_PROFILE
from body_sim.model import BodyState


@pytest.fixture
def initial_state():
    return BodyState(fat_mass_kg=20.0, lean_mass_kg=60.0)


@pytest.fixture
def maintenance_inputs_30d():
    return [
        {
            "intake_kcal": 2500.0,
            "protein_g": 120.0,
            "carb_g": 300.0,
            "fat_g": 75.0,
            "sodium_mg": 2300.0,
            "ee_hr_keytel_kcal": 600.0,
            "workout_kcal": 0.0,
            "vigorous_min": 0,
            "intake_logged": True,
            "hr_coverage_pct": 100.0,
            "steps": 8000,
        }
        for _ in range(30)
    ]


def test_simulate_forward_shape(initial_state, maintenance_inputs_30d):
    samples = simulate.sample_parameters(n=50, base=DEFAULT_PARAMETERS, seed=0)
    result = simulate.simulate_forward(
        initial_state=initial_state,
        inputs_per_day=maintenance_inputs_30d,
        profile=DEFAULT_PROFILE,
        parameter_samples=samples,
    )
    # 50 samples, 30 days, multiple tracked quantities
    assert result.predicted_weight_kg.shape == (50, 30)
    assert result.fat_mass_kg.shape == (50, 30)
    assert result.lean_mass_kg.shape == (50, 30)


def test_simulate_forward_maintenance_is_stable(initial_state, maintenance_inputs_30d):
    samples = simulate.sample_parameters(n=20, base=DEFAULT_PARAMETERS, seed=1)
    result = simulate.simulate_forward(
        initial_state=initial_state,
        inputs_per_day=maintenance_inputs_30d,
        profile=DEFAULT_PROFILE,
        parameter_samples=samples,
    )
    # At rough maintenance, total mass changes < 1 kg over 30 days on average
    mean_change = float(np.mean(result.predicted_weight_kg[:, -1] - result.predicted_weight_kg[:, 0]))
    assert abs(mean_change) < 2.0


def test_simulate_forward_deficit_loses_weight(initial_state):
    inputs = [
        {
            "intake_kcal": 1500.0,
            "protein_g": 120.0,
            "carb_g": 150.0,
            "fat_g": 50.0,
            "sodium_mg": 2300.0,
            "ee_hr_keytel_kcal": 700.0,
            "workout_kcal": 0.0,
            "vigorous_min": 0,
            "intake_logged": True,
            "hr_coverage_pct": 100.0,
            "steps": 8000,
        }
        for _ in range(56)
    ]
    samples = simulate.sample_parameters(n=20, base=DEFAULT_PARAMETERS, seed=2)
    result = simulate.simulate_forward(
        initial_state=initial_state,
        inputs_per_day=inputs,
        profile=DEFAULT_PROFILE,
        parameter_samples=samples,
    )
    mean_final = float(np.mean(result.predicted_weight_kg[:, -1]))
    initial_weight = initial_state.predicted_weight_kg(sodium_mg=2300.0)
    assert mean_final < initial_weight - 2.0


def test_sample_parameters_reproducible():
    a = simulate.sample_parameters(n=10, base=DEFAULT_PARAMETERS, seed=42)
    b = simulate.sample_parameters(n=10, base=DEFAULT_PARAMETERS, seed=42)
    for k in DEFAULT_PARAMETERS:
        assert np.array_equal(a[k], b[k])


def test_credible_band_shape():
    arr = np.random.normal(loc=80, scale=1, size=(200, 30))
    band = simulate.credible_band(arr, lo=0.025, hi=0.975)
    assert band["lo"].shape == (30,)
    assert band["hi"].shape == (30,)
    assert (band["hi"] > band["lo"]).all()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_simulate.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/simulate.py`**

```python
"""Forward simulation of body-composition trajectories.

Repeatedly applies `model.step` to roll the state forward N days under a given
input series, once per parameter sample. Returns arrays of shape (n_samples,
n_days) for each tracked quantity, plus helpers to compute credible bands.
"""

from dataclasses import dataclass

import numpy as np

from body_sim import model
from body_sim.config import DEFAULT_PARAMETERS, UserProfile


# Width of Gaussian prior around each population-default parameter
PRIOR_SDS = {
    "intake_bias": 0.10,
    "RMR_scale": 0.05,
    "NEAT_response": 0.10,
    "protein_protection": 0.20,
    "activity_bias": 0.10,
    "water_noise_sd": 0.2,
}


def sample_parameters(
    n: int, base: dict | None = None, seed: int | None = None
) -> dict[str, np.ndarray]:
    """Draw `n` independent samples from each parameter's population prior.

    Returns a dict mapping parameter name to a length-n NumPy array.
    """
    if base is None:
        base = DEFAULT_PARAMETERS
    rng = np.random.default_rng(seed)
    return {
        name: rng.normal(loc=base[name], scale=PRIOR_SDS[name], size=n)
        for name in PRIOR_SDS
    }


@dataclass
class SimulationResult:
    predicted_weight_kg: np.ndarray   # shape (n_samples, n_days)
    fat_mass_kg: np.ndarray
    lean_mass_kg: np.ndarray
    body_fat_pct: np.ndarray
    delta_e_kcal: np.ndarray
    expenditure_kcal: np.ndarray


def simulate_forward(
    initial_state: model.BodyState,
    inputs_per_day: list[dict],
    profile: UserProfile,
    parameter_samples: dict[str, np.ndarray],
) -> SimulationResult:
    """Roll the model forward over the input series, once per parameter sample."""
    n_samples = next(iter(parameter_samples.values())).shape[0]
    n_days = len(inputs_per_day)

    predicted = np.zeros((n_samples, n_days))
    fat = np.zeros((n_samples, n_days))
    lean = np.zeros((n_samples, n_days))
    bf_pct = np.zeros((n_samples, n_days))
    de = np.zeros((n_samples, n_days))
    ee = np.zeros((n_samples, n_days))

    for s in range(n_samples):
        params = {name: float(parameter_samples[name][s]) for name in parameter_samples}
        state = model.BodyState(
            fat_mass_kg=initial_state.fat_mass_kg,
            lean_mass_kg=initial_state.lean_mass_kg,
            glycogen_g=initial_state.glycogen_g,
        )
        for d, inputs in enumerate(inputs_per_day):
            state, diag = model.step(state=state, inputs=inputs, profile=profile, parameters=params)
            predicted[s, d] = diag["predicted_weight_kg"]
            fat[s, d] = state.fat_mass_kg
            lean[s, d] = state.lean_mass_kg
            bf_pct[s, d] = state.body_fat_pct()
            de[s, d] = diag["delta_e_kcal"]
            ee[s, d] = diag["expenditure_kcal"]
    return SimulationResult(
        predicted_weight_kg=predicted,
        fat_mass_kg=fat,
        lean_mass_kg=lean,
        body_fat_pct=bf_pct,
        delta_e_kcal=de,
        expenditure_kcal=ee,
    )


def credible_band(
    arr: np.ndarray, lo: float = 0.025, hi: float = 0.975
) -> dict[str, np.ndarray]:
    """Per-day quantile band across the sample axis."""
    return {
        "lo": np.quantile(arr, lo, axis=0),
        "median": np.quantile(arr, 0.5, axis=0),
        "hi": np.quantile(arr, hi, axis=0),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_simulate.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/simulate.py tests/body_sim/test_simulate.py
git commit -m "feat(body_sim): forward-simulate trajectories with prior-sample bands"
```

---

## Task 16: Forward-walking validation harness

**Files:**
- Create: `body_sim/validation.py`
- Test: `tests/body_sim/test_validation.py`

`forward_walk(df, step_days, profile, sample_n)` — iterates through the daily-rollup DataFrame in `step_days`-day chunks, simulating each chunk forward from the last observed state, and returns a long-form DataFrame of (date, sample, predicted_weight, observed_weight, ...) suitable for the validation plots.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_validation.py`:

```python
import datetime

import numpy as np
import pandas as pd
import pytest

from body_sim import validation
from body_sim.config import DEFAULT_PROFILE


def _synthetic_rollup(n_days: int, base_weight: float = 80.0) -> pd.DataFrame:
    """Synthetic daily rollup with maintenance-ish inputs."""
    idx = pd.date_range(start="2026-05-01", periods=n_days, freq="D")
    weights = base_weight + np.linspace(0, -0.5, n_days)  # tiny linear loss
    return pd.DataFrame(
        {
            "intake_kcal": 2400.0,
            "protein_g": 120.0,
            "carb_g": 280.0,
            "fat_g": 75.0,
            "sodium_mg": 2300.0,
            "ee_hr_keytel_kcal": 600.0,
            "workout_kcal": 0.0,
            "vigorous_min": 0,
            "intake_logged": True,
            "hr_coverage_pct": 100.0,
            "steps": 8000,
            "weight_kg": np.where(np.arange(n_days) % 2 == 0, weights, np.nan),
            "bf_pct": np.nan,
            "reference_weight_kg": base_weight,
        },
        index=idx,
    )


def test_forward_walk_returns_long_dataframe():
    df = _synthetic_rollup(n_days=14)
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=10, seed=0
    )
    assert "predicted_weight_kg" in out.columns
    assert "observed_weight_kg" in out.columns
    assert "sample" in out.columns
    assert "date" in out.columns
    assert len(out) > 0


def test_forward_walk_covers_all_dates_after_seed():
    df = _synthetic_rollup(n_days=21)
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=5, seed=0
    )
    # We seed initial state from the first observed weight, then walk forward.
    unique_dates = out["date"].unique()
    assert len(unique_dates) >= 7  # at least one full chunk worth of predictions


def test_forward_walk_observed_aligned():
    df = _synthetic_rollup(n_days=14)
    out = validation.forward_walk(
        df, step_days=7, profile=DEFAULT_PROFILE, sample_n=2, seed=0
    )
    # Observed weights should match the source DataFrame for the dates where we have them
    for _, row in out.iterrows():
        d = row["date"]
        if pd.notna(row["observed_weight_kg"]):
            assert row["observed_weight_kg"] == pytest.approx(df.loc[d, "weight_kg"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_validation.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/validation.py`**

```python
"""Forward-walking validation harness.

Walks through the daily-rollup DataFrame in `step_days`-sized chunks. For each
chunk: seed initial state from the most recent observed weight (or carry forward
the simulated state if no recent weigh-in), simulate forward N days drawing
parameter samples from the prior, record (date, sample, predicted, observed)
tuples for later evaluation and plotting.
"""

import numpy as np
import pandas as pd

from body_sim import model, simulate
from body_sim.config import DEFAULT_PROFILE, UserProfile


INPUT_COLUMNS = [
    "intake_kcal", "protein_g", "carb_g", "fat_g", "sodium_mg",
    "ee_hr_keytel_kcal", "workout_kcal", "vigorous_min", "intake_logged",
    "hr_coverage_pct", "steps",
]


def _seed_state(reference_weight: float, target_bf_pct: float = 22.0) -> model.BodyState:
    """Seed initial body composition from a weight observation.

    At Phase 1 we use a fixed bf% prior; future phases personalize this from
    the user's own observed bf%.
    """
    fat = reference_weight * (target_bf_pct / 100.0)
    lean = reference_weight - fat
    return model.BodyState(fat_mass_kg=fat, lean_mass_kg=lean)


def _row_to_input(row: pd.Series) -> dict:
    inputs = {col: row[col] for col in INPUT_COLUMNS}
    # Coerce types
    for k in ("intake_kcal", "protein_g", "carb_g", "fat_g", "sodium_mg",
              "ee_hr_keytel_kcal", "workout_kcal", "hr_coverage_pct"):
        v = inputs[k]
        inputs[k] = 0.0 if pd.isna(v) else float(v)
    inputs["vigorous_min"] = 0 if pd.isna(inputs["vigorous_min"]) else int(inputs["vigorous_min"])
    inputs["steps"] = 0 if pd.isna(inputs["steps"]) else int(inputs["steps"])
    inputs["intake_logged"] = bool(inputs["intake_logged"])
    return inputs


def forward_walk(
    df: pd.DataFrame,
    step_days: int,
    profile: UserProfile,
    sample_n: int,
    seed: int | None = None,
) -> pd.DataFrame:
    """Forward-walking validation over the rollup DataFrame.

    Args:
        df: daily-rollup DataFrame (output of pipeline.build_daily_rollup)
        step_days: chunk size for the walk
        profile: user profile
        sample_n: number of parameter samples per chunk
        seed: RNG seed

    Returns:
        Long-form DataFrame with columns date, sample, predicted_weight_kg,
        observed_weight_kg, fat_mass_kg, lean_mass_kg.
    """
    if df.empty:
        return pd.DataFrame()

    samples = simulate.sample_parameters(n=sample_n, seed=seed)
    records: list[dict] = []

    # First observation (or fallback) seeds the initial state
    first_observed_idx = df["weight_kg"].first_valid_index()
    if first_observed_idx is None:
        seed_weight = float(df["reference_weight_kg"].iloc[0])
    else:
        seed_weight = float(df.loc[first_observed_idx, "weight_kg"])
    initial = _seed_state(seed_weight)

    cur_idx = df.index[0] if first_observed_idx is None else first_observed_idx
    while cur_idx < df.index[-1]:
        end_idx_pos = min(
            len(df) - 1,
            df.index.get_loc(cur_idx) + step_days,
        )
        end_idx = df.index[end_idx_pos]
        chunk = df.loc[cur_idx:end_idx]
        inputs_per_day = [_row_to_input(row) for _, row in chunk.iterrows()]
        result = simulate.simulate_forward(
            initial_state=initial,
            inputs_per_day=inputs_per_day,
            profile=profile,
            parameter_samples=samples,
        )
        for s in range(sample_n):
            for d_offset, ts in enumerate(chunk.index):
                records.append(
                    {
                        "date": ts,
                        "sample": s,
                        "predicted_weight_kg": float(result.predicted_weight_kg[s, d_offset]),
                        "observed_weight_kg": (
                            float(chunk.iloc[d_offset]["weight_kg"])
                            if pd.notna(chunk.iloc[d_offset]["weight_kg"])
                            else np.nan
                        ),
                        "fat_mass_kg": float(result.fat_mass_kg[s, d_offset]),
                        "lean_mass_kg": float(result.lean_mass_kg[s, d_offset]),
                        "body_fat_pct": float(result.body_fat_pct[s, d_offset]),
                    }
                )
        # Next chunk: re-seed from the most recent observed weight in this chunk if any
        weighed = chunk["weight_kg"].dropna()
        if not weighed.empty:
            initial = _seed_state(float(weighed.iloc[-1]))
        cur_idx = end_idx + pd.Timedelta(days=1)

    return pd.DataFrame(records)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_validation.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/validation.py tests/body_sim/test_validation.py
git commit -m "feat(body_sim): forward-walking validation harness"
```

---

## Task 17: Evaluation metrics

**Files:**
- Create: `body_sim/evaluate.py`
- Test: `tests/body_sim/test_evaluate.py`

MAE, calibration coverage (fraction of observations inside the 95% predictive band), Kendall's tau on residuals (drift check). All return floats; thresholds defined in `config` for reuse in plotting.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_evaluate.py`:

```python
import numpy as np
import pandas as pd
import pytest

from body_sim import evaluate


def _walk_df(predicted_means, observed):
    """Synthetic walk DataFrame: 10 samples per date, all at the mean."""
    rows = []
    for d, (pm, obs) in enumerate(zip(predicted_means, observed)):
        for s in range(10):
            rows.append(
                {
                    "date": pd.Timestamp("2026-05-01") + pd.Timedelta(days=d),
                    "sample": s,
                    "predicted_weight_kg": pm + np.random.normal(0, 0.3),
                    "observed_weight_kg": obs,
                }
            )
    return pd.DataFrame(rows)


def test_mae_on_perfect_predictions():
    df = _walk_df([80.0, 80.0, 80.0], [80.0, 80.0, 80.0])
    assert evaluate.mae(df) < 0.5  # noise from synthetic samples


def test_mae_on_off_predictions():
    df = _walk_df([80.0, 80.0, 80.0], [82.0, 82.0, 82.0])
    assert evaluate.mae(df) > 1.5


def test_calibration_coverage_high_when_predictions_good():
    df = _walk_df([80.0] * 30, [80.0 + np.random.normal(0, 0.2) for _ in range(30)])
    cov = evaluate.calibration_coverage(df)
    assert cov >= 0.8


def test_calibration_coverage_low_when_systematically_off():
    df = _walk_df([80.0] * 30, [85.0] * 30)
    cov = evaluate.calibration_coverage(df)
    assert cov < 0.2


def test_residual_drift_p_value():
    # No drift: residuals stationary around 0
    df = _walk_df([80.0] * 20, [80.0 + np.random.normal(0, 0.3) for _ in range(20)])
    p = evaluate.residual_drift_p_value(df)
    assert p > 0.05


def test_residual_drift_detects_monotonic():
    # Strong drift: predictions stay flat, observations rise linearly
    df = _walk_df([80.0] * 20, list(80.0 + np.linspace(0, 4, 20)))
    p = evaluate.residual_drift_p_value(df)
    assert p < 0.05


def test_summary_report_includes_all_metrics():
    df = _walk_df([80.0] * 10, [80.5] * 10)
    rep = evaluate.summary_report(df)
    for key in ("mae", "calibration_coverage", "residual_drift_p", "n_observations"):
        assert key in rep
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_evaluate.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/evaluate.py`**

```python
"""Evaluation metrics for body-composition forecasts.

All functions accept a long-form DataFrame as produced by
`validation.forward_walk` and return scalar metrics.
"""

import numpy as np
import pandas as pd
from scipy import stats


def _aggregate_to_per_day(walk_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-day median prediction + 95% band + observed."""
    grouped = walk_df.groupby("date")
    return pd.DataFrame(
        {
            "predicted_median": grouped["predicted_weight_kg"].median(),
            "predicted_lo": grouped["predicted_weight_kg"].quantile(0.025),
            "predicted_hi": grouped["predicted_weight_kg"].quantile(0.975),
            "observed": grouped["observed_weight_kg"].first(),
        }
    ).reset_index()


def mae(walk_df: pd.DataFrame) -> float:
    """Mean absolute error between median prediction and observed weight."""
    per_day = _aggregate_to_per_day(walk_df).dropna(subset=["observed"])
    if per_day.empty:
        return float("nan")
    return float(np.mean(np.abs(per_day["predicted_median"] - per_day["observed"])))


def calibration_coverage(walk_df: pd.DataFrame) -> float:
    """Fraction of observed values inside the 95% predictive band."""
    per_day = _aggregate_to_per_day(walk_df).dropna(subset=["observed"])
    if per_day.empty:
        return float("nan")
    inside = (per_day["observed"] >= per_day["predicted_lo"]) & (
        per_day["observed"] <= per_day["predicted_hi"]
    )
    return float(inside.mean())


def residual_drift_p_value(walk_df: pd.DataFrame) -> float:
    """Kendall's tau p-value testing for monotonic residual drift over time."""
    per_day = _aggregate_to_per_day(walk_df).dropna(subset=["observed"])
    if len(per_day) < 5:
        return float("nan")
    residuals = per_day["observed"] - per_day["predicted_median"]
    day_index = np.arange(len(residuals))
    tau, p = stats.kendalltau(day_index, residuals.values)
    return float(p)


def summary_report(walk_df: pd.DataFrame) -> dict[str, float | int]:
    """Combined metrics dict for use in notebook output."""
    per_day = _aggregate_to_per_day(walk_df).dropna(subset=["observed"])
    return {
        "mae": mae(walk_df),
        "calibration_coverage": calibration_coverage(walk_df),
        "residual_drift_p": residual_drift_p_value(walk_df),
        "n_observations": int(len(per_day)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_evaluate.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/evaluate.py tests/body_sim/test_evaluate.py
git commit -m "feat(body_sim): evaluation metrics (MAE, calibration coverage, drift)"
```

---

## Task 18: Plotting functions

**Files:**
- Create: `body_sim/plotting.py`
- Test: `tests/body_sim/test_plotting.py`

Three required plots from the spec. Functions return `matplotlib.figure.Figure` so notebooks display them directly. Tests verify the figures are produced without errors and have plausible axis labels.

- [ ] **Step 1: Write failing tests**

Create `tests/body_sim/test_plotting.py`:

```python
import numpy as np
import pandas as pd
import pytest
import matplotlib

matplotlib.use("Agg")

from body_sim import plotting


def _walk_df(n_days: int = 30) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(0)
    for d in range(n_days):
        for s in range(20):
            rows.append(
                {
                    "date": pd.Timestamp("2026-05-01") + pd.Timedelta(days=d),
                    "sample": s,
                    "predicted_weight_kg": 80 + rng.normal(0, 0.5),
                    "observed_weight_kg": 80.2 if d % 2 == 0 else np.nan,
                    "body_fat_pct": 22 + rng.normal(0, 0.3),
                }
            )
    return pd.DataFrame(rows)


def test_trajectory_plot_returns_figure():
    walk = _walk_df()
    fig = plotting.trajectory_plot(walk, metric="weight")
    assert fig is not None
    ax = fig.axes[0]
    assert "kg" in ax.get_ylabel().lower() or "weight" in ax.get_ylabel().lower()


def test_trajectory_plot_bf_metric():
    walk = _walk_df()
    fig = plotting.trajectory_plot(walk, metric="bf")
    assert fig is not None


def test_residual_plot_returns_figure():
    walk = _walk_df()
    fig = plotting.residual_plot(walk)
    assert fig is not None
    ax = fig.axes[0]
    # Reference lines at ±0.5 kg are drawn
    horizontal_lines = [line for line in ax.lines if line.get_linestyle() in ("--", ":")]
    assert len(horizontal_lines) >= 2


def test_three_panel_summary_returns_figure():
    walk = _walk_df()
    fig = plotting.three_panel_summary(walk)
    assert len(fig.axes) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/body_sim/test_plotting.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `body_sim/plotting.py`**

```python
"""The three required validation plots.

Imported by notebooks 03 and 04. All functions return a matplotlib Figure
so the notebook just needs to assign the return value to display it.
"""

from typing import Literal

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _aggregate(walk_df: pd.DataFrame, metric: str) -> pd.DataFrame:
    pred_col = "body_fat_pct" if metric == "bf" else "predicted_weight_kg"
    obs_col = "observed_weight_kg"  # bf observed handled separately when available
    grouped = walk_df.groupby("date")
    out = pd.DataFrame(
        {
            "median": grouped[pred_col].median(),
            "lo": grouped[pred_col].quantile(0.025),
            "hi": grouped[pred_col].quantile(0.975),
            "observed": grouped[obs_col].first() if metric == "weight" else np.nan,
        }
    ).reset_index()
    return out


def trajectory_plot(
    walk_df: pd.DataFrame, metric: Literal["weight", "bf"] = "weight"
) -> plt.Figure:
    """Predicted trajectory with 95% band + observed dots overlaid."""
    agg = _aggregate(walk_df, metric)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(agg["date"], agg["lo"], agg["hi"], alpha=0.2, label="95% predictive band")
    ax.plot(agg["date"], agg["median"], label="Predicted median", linewidth=2)
    if metric == "weight":
        observed = agg.dropna(subset=["observed"])
        ax.scatter(observed["date"], observed["observed"], color="black", zorder=5, label="Observed")
        ax.set_ylabel("Body weight (kg)")
        ax.set_title("Predicted weight trajectory vs. observed weigh-ins")
    else:
        ax.set_ylabel("Body fat (%)")
        ax.set_title("Predicted body-fat trajectory")
    ax.set_xlabel("Date")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def residual_plot(walk_df: pd.DataFrame) -> plt.Figure:
    """Residual time-series: observed − predicted median, with ±0.5 kg refs."""
    agg = _aggregate(walk_df, "weight").dropna(subset=["observed"])
    residuals = agg["observed"] - agg["median"]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.scatter(agg["date"], residuals, color="black")
    ax.axhline(0, color="gray", linewidth=1)
    ax.axhline(0.5, color="red", linestyle="--", linewidth=1, label="±0.5 kg scale noise")
    ax.axhline(-0.5, color="red", linestyle="--", linewidth=1)
    ax.set_xlabel("Date")
    ax.set_ylabel("Residual (observed − predicted), kg")
    ax.set_title("Residual time-series")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def three_panel_summary(walk_df: pd.DataFrame) -> plt.Figure:
    """Three required plots stacked vertically for the validation overview."""
    fig, axes = plt.subplots(3, 1, figsize=(10, 12))
    # Re-render each plot on the shared figure axes
    weight_agg = _aggregate(walk_df, "weight")
    axes[0].fill_between(weight_agg["date"], weight_agg["lo"], weight_agg["hi"], alpha=0.2)
    axes[0].plot(weight_agg["date"], weight_agg["median"], linewidth=2)
    obs = weight_agg.dropna(subset=["observed"])
    axes[0].scatter(obs["date"], obs["observed"], color="black", zorder=5)
    axes[0].set_ylabel("Weight (kg)")
    axes[0].set_title("Weight trajectory")

    bf_agg = _aggregate(walk_df, "bf")
    axes[1].fill_between(bf_agg["date"], bf_agg["lo"], bf_agg["hi"], alpha=0.2)
    axes[1].plot(bf_agg["date"], bf_agg["median"], linewidth=2)
    axes[1].set_ylabel("Body fat (%)")
    axes[1].set_title("Body fat trajectory")

    res = obs["observed"] - obs["median"]
    axes[2].scatter(obs["date"], res, color="black")
    axes[2].axhline(0, color="gray")
    axes[2].axhline(0.5, color="red", linestyle="--")
    axes[2].axhline(-0.5, color="red", linestyle="--")
    axes[2].set_ylabel("Residual (kg)")
    axes[2].set_title("Residual time-series")

    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/body_sim/test_plotting.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add body_sim/plotting.py tests/body_sim/test_plotting.py
git commit -m "feat(body_sim): trajectory, residual, and three-panel plots"
```

---

## Task 19: Notebook 02 — data pipeline

**Files:**
- Create: `notebooks/02_data_pipeline.ipynb`

This is a thin notebook that imports `body_sim.pipeline`, runs `build_daily_rollup` against the live foodlog DB, and displays a summary. The intent is to make the pipeline output legible (does each column look sane?) before we start modeling on top of it.

- [ ] **Step 1: Create the notebook with explicit cell content**

Create `notebooks/02_data_pipeline.ipynb` using a small Python script. From the project root:

```bash
python - <<'PY'
import json
from pathlib import Path

cells = [
    {
        "cell_type": "markdown",
        "source": [
            "# 02 — Data Pipeline\n",
            "\n",
            "Builds the canonical daily-rollup DataFrame for the body-composition simulator.\n",
            "Run this first. Notebooks 03 (EDA), 04 (Hall baseline), 06 (simulator), and 07 (live tracking) all consume the output of this notebook.\n",
            "\n",
            "Reference: `docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md`",
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import datetime\n",
            "import sys\n",
            "from pathlib import Path\n",
            "\n",
            "REPO_ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n",
            "sys.path.insert(0, str(REPO_ROOT))\n",
            "\n",
            "from body_sim.config import DEFAULT_PROFILE\n",
            "from body_sim.pipeline import build_daily_rollup\n",
            "from foodlog.db.database import get_session_factory\n",
            "\n",
            "session = get_session_factory()()",
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "# Date range — defaults to last 60 days. Adjust as needed.\n",
            "end = datetime.date.today()\n",
            "start = end - datetime.timedelta(days=60)\n",
            "\n",
            "df = build_daily_rollup(\n",
            "    session=session,\n",
            "    start=start,\n",
            "    end=end,\n",
            "    weight_kg_fallback=80.0,\n",
            "    age=DEFAULT_PROFILE['age'],\n",
            "    sex=DEFAULT_PROFILE['sex'],\n",
            ")\n",
            "df.head()",
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "# Summary stats\n",
            "import pandas as pd\n",
            "pd.set_option('display.max_columns', None)\n",
            "\n",
            "summary = df.describe(include='all').T\n",
            "summary['missing_count'] = df.isna().sum()\n",
            "summary[['count', 'mean', 'std', 'min', 'max', 'missing_count']]",
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "# Save as a parquet artifact for downstream notebooks\n",
            "artifact_path = REPO_ROOT / 'notebooks' / 'predictions' / 'daily_rollup.parquet'\n",
            "df.to_parquet(artifact_path)\n",
            "print(f'Saved {len(df)} rows to {artifact_path}')",
        ],
    },
]

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

Path('notebooks/02_data_pipeline.ipynb').write_text(json.dumps(nb, indent=1))
print("Wrote notebooks/02_data_pipeline.ipynb")
PY
```

- [ ] **Step 2: Execute the notebook to verify it runs end-to-end**

```bash
jupyter nbconvert --to notebook --execute notebooks/02_data_pipeline.ipynb \
    --output 02_data_pipeline.ipynb --ExecutePreprocessor.timeout=300
```

Expected: completes without errors. A `notebooks/predictions/daily_rollup.parquet` file is created.

- [ ] **Step 3: Commit**

```bash
git add notebooks/02_data_pipeline.ipynb notebooks/predictions/daily_rollup.parquet
git commit -m "feat(body_sim): notebook 02 — data pipeline producing daily-rollup parquet"
```

---

## Task 20: Notebook 03 — descriptive EDA

**Files:**
- Create: `notebooks/03_descriptive_eda.ipynb`

Plots:
1. Missingness heatmap across all columns
2. Energy balance over time (intake vs expenditure estimates)
3. Weight series with raw points and the inferred glycogen+sodium water decomposition
4. HR coverage histogram
5. Meal-type coverage distribution

- [ ] **Step 1: Write the notebook**

```bash
python - <<'PY'
import json
from pathlib import Path

cells = [
    {
        "cell_type": "markdown",
        "source": [
            "# 03 — Descriptive EDA\n",
            "\n",
            "Visual inspection of the daily-rollup output from notebook 02. The goal is to make data-quality issues visible before any modeling.",
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import sys\n",
            "from pathlib import Path\n",
            "import pandas as pd\n",
            "import numpy as np\n",
            "import matplotlib.pyplot as plt\n",
            "\n",
            "REPO_ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n",
            "sys.path.insert(0, str(REPO_ROOT))\n",
            "\n",
            "df = pd.read_parquet(REPO_ROOT / 'notebooks' / 'predictions' / 'daily_rollup.parquet')\n",
            "df.head()",
        ],
    },
    {
        "cell_type": "markdown",
        "source": ["## Missingness map"],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import matplotlib.pyplot as plt\n",
            "fig, ax = plt.subplots(figsize=(12, 8))\n",
            "missing_matrix = df.isna().astype(int).T\n",
            "ax.imshow(missing_matrix.values, aspect='auto', cmap='Greys', interpolation='nearest')\n",
            "ax.set_yticks(range(len(missing_matrix.index)))\n",
            "ax.set_yticklabels(missing_matrix.index)\n",
            "ax.set_xticks(range(0, len(df), max(1, len(df)//10)))\n",
            "ax.set_xticklabels([d.strftime('%m-%d') for d in df.index[::max(1, len(df)//10)]], rotation=45)\n",
            "ax.set_title('Missingness map (black = NaN)')\n",
            "plt.tight_layout()\n",
            "plt.show()",
        ],
    },
    {
        "cell_type": "markdown",
        "source": ["## HR coverage and intake coverage distributions"],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "fig, axes = plt.subplots(1, 2, figsize=(12, 4))\n",
            "axes[0].hist(df['hr_coverage_pct'].dropna(), bins=20)\n",
            "axes[0].set_xlabel('HR coverage (%)')\n",
            "axes[0].set_ylabel('Days')\n",
            "axes[0].set_title('HR coverage distribution')\n",
            "axes[0].axvline(50, color='red', linestyle='--', label='Keytel cutoff')\n",
            "axes[0].legend()\n",
            "\n",
            "axes[1].hist(df['intake_coverage'], bins=[0, 0.33, 0.67, 1.01])\n",
            "axes[1].set_xlabel('Intake coverage (0=nothing, 1=B+L+D)')\n",
            "axes[1].set_ylabel('Days')\n",
            "axes[1].set_title('Meal-type coverage distribution')\n",
            "plt.tight_layout()\n",
            "plt.show()",
        ],
    },
    {
        "cell_type": "markdown",
        "source": ["## Weight series with running mean"],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "fig, ax = plt.subplots(figsize=(12, 5))\n",
            "weighed = df.dropna(subset=['weight_kg'])\n",
            "ax.scatter(weighed.index, weighed['weight_kg'], label='Observed')\n",
            "if len(weighed) >= 3:\n",
            "    ax.plot(weighed.index, weighed['weight_kg'].rolling(7, min_periods=1).mean(), label='7-day rolling mean')\n",
            "ax.set_ylabel('Weight (kg)')\n",
            "ax.set_xlabel('Date')\n",
            "ax.set_title('Observed weight with 7-day rolling mean')\n",
            "ax.legend()\n",
            "ax.grid(alpha=0.3)\n",
            "plt.tight_layout()\n",
            "plt.show()",
        ],
    },
    {
        "cell_type": "markdown",
        "source": ["## Energy balance proxy (intake vs daily activity + workouts)"],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "from body_sim.rmr import mifflin_st_jeor\n",
            "from body_sim.config import DEFAULT_PROFILE\n",
            "\n",
            "df = df.copy()\n",
            "df['rmr_estimate'] = df['reference_weight_kg'].apply(\n",
            "    lambda w: mifflin_st_jeor(w, DEFAULT_PROFILE['height_cm'], DEFAULT_PROFILE['age'], DEFAULT_PROFILE['sex'])\n",
            ")\n",
            "df['activity_estimate'] = df['ee_hr_keytel_kcal'].fillna(df['workout_kcal'] + df['steps'].fillna(0) * 0.04)\n",
            "df['expenditure_estimate'] = df['rmr_estimate'] + df['activity_estimate']\n",
            "fig, ax = plt.subplots(figsize=(12, 5))\n",
            "ax.plot(df.index, df['intake_kcal'], label='Intake (logged)', marker='o', linewidth=1)\n",
            "ax.plot(df.index, df['expenditure_estimate'], label='Expenditure (est.)', marker='s', linewidth=1)\n",
            "ax.set_ylabel('kcal/day')\n",
            "ax.set_xlabel('Date')\n",
            "ax.set_title('Energy balance (proxy — pre-model)')\n",
            "ax.legend()\n",
            "ax.grid(alpha=0.3)\n",
            "plt.tight_layout()\n",
            "plt.show()",
        ],
    },
]

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

Path('notebooks/03_descriptive_eda.ipynb').write_text(json.dumps(nb, indent=1))
print("Wrote notebooks/03_descriptive_eda.ipynb")
PY
```

- [ ] **Step 2: Execute to verify**

```bash
jupyter nbconvert --to notebook --execute notebooks/03_descriptive_eda.ipynb \
    --output 03_descriptive_eda.ipynb --ExecutePreprocessor.timeout=300
```

Expected: completes without errors.

- [ ] **Step 3: Commit**

```bash
git add notebooks/03_descriptive_eda.ipynb
git commit -m "feat(body_sim): notebook 03 — descriptive EDA with missingness map"
```

---

## Task 21: Notebook 04 — Hall baseline (population defaults)

**Files:**
- Create: `notebooks/04_hall_baseline.ipynb`

This runs `validation.forward_walk` over the daily-rollup, renders the three required plots, and prints the summary metrics. It is the answer to the question "does the population-default model track this user's data?"

- [ ] **Step 1: Write the notebook**

```bash
python - <<'PY'
import json
from pathlib import Path

cells = [
    {
        "cell_type": "markdown",
        "source": [
            "# 04 — Hall Baseline\n",
            "\n",
            "Forward-walking validation of the extended Hall energy-balance model with **population-default parameters**. No personalization yet — that's Phase 2.\n",
            "\n",
            "Renders the three required plots (weight trajectory + 95% band, body-fat trajectory, residual time-series) and prints the summary metrics (MAE, calibration coverage, drift p-value)."
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import sys\n",
            "from pathlib import Path\n",
            "import pandas as pd\n",
            "import matplotlib.pyplot as plt\n",
            "\n",
            "REPO_ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n",
            "sys.path.insert(0, str(REPO_ROOT))\n",
            "\n",
            "from body_sim.config import DEFAULT_PROFILE\n",
            "from body_sim import validation, evaluate, plotting\n",
            "\n",
            "df = pd.read_parquet(REPO_ROOT / 'notebooks' / 'predictions' / 'daily_rollup.parquet')\n",
            "df.head()"
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "walk = validation.forward_walk(\n",
            "    df, step_days=7, profile=DEFAULT_PROFILE, sample_n=200, seed=42\n",
            ")\n",
            "walk.head()"
        ],
    },
    {
        "cell_type": "markdown",
        "source": ["## Summary metrics"],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "rep = evaluate.summary_report(walk)\n",
            "print(f'MAE:                   {rep[\"mae\"]:.3f} kg')\n",
            "print(f'95% calibration:       {100*rep[\"calibration_coverage\"]:.1f}% of observed weigh-ins inside band')\n",
            "print(f'Residual drift p-value: {rep[\"residual_drift_p\"]:.3f}')\n",
            "print(f'Observations used:      {rep[\"n_observations\"]}')\n",
            "\n",
            "print()\n",
            "print('Phase 1 passing thresholds:')\n",
            "print(f'  MAE < 1.0 kg:                 {\"PASS\" if rep[\"mae\"] < 1.0 else \"FAIL\"}')\n",
            "print(f'  Calibration >= 80%:           {\"PASS\" if rep[\"calibration_coverage\"] >= 0.8 else \"FAIL\"}')\n",
            "print(f'  No drift (p > 0.1):           {\"PASS\" if rep[\"residual_drift_p\"] > 0.1 else \"FAIL\"}')"
        ],
    },
    {
        "cell_type": "markdown",
        "source": ["## The three required plots"],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": ["fig = plotting.trajectory_plot(walk, metric='weight')\nplt.show()"],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": ["fig = plotting.trajectory_plot(walk, metric='bf')\nplt.show()"],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": ["fig = plotting.residual_plot(walk)\nplt.show()"],
    },
    {
        "cell_type": "markdown",
        "source": [
            "## Diagnostic interpretation\n",
            "\n",
            "If any of the passing thresholds above FAILED, the residual plot is the diagnostic to read. Specifically:\n",
            "\n",
            "- **Systematic positive residual (observed > predicted everywhere)**: intake is being under-reported. `intake_bias` (Phase 2) will compensate.\n",
            "- **Monotonic drift over time**: adaptive thermogenesis isn't capturing prolonged-deficit metabolic adaptation. Could motivate Phase 3 NEAT_response.\n",
            "- **High-variance residuals correlated with carb-heavy days**: glycogen-water dynamics need tuning.\n",
            "- **Spikes correlated with sodium-heavy days**: sodium-water dynamics need tuning.\n",
            "\n",
            "Note any patterns here as starting hypotheses for Phase 2."
        ],
    },
]

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

Path('notebooks/04_hall_baseline.ipynb').write_text(json.dumps(nb, indent=1))
print("Wrote notebooks/04_hall_baseline.ipynb")
PY
```

- [ ] **Step 2: Execute to verify**

```bash
jupyter nbconvert --to notebook --execute notebooks/04_hall_baseline.ipynb \
    --output 04_hall_baseline.ipynb --ExecutePreprocessor.timeout=300
```

Expected: completes without errors. Output cells show validation metrics and three plots.

- [ ] **Step 3: Commit**

```bash
git add notebooks/04_hall_baseline.ipynb
git commit -m "feat(body_sim): notebook 04 — Hall baseline with three required plots"
```

---

## Task 22: Notebook 06 — scenario simulator with ipywidgets

**Files:**
- Create: `notebooks/06_scenario_simulator.ipynb`

The headline deliverable. Sliders for `intake_kcal / protein_g / carb_g / fat_g / sodium_mg / steps / vigorous_min / horizon_days`. Live re-render of the predicted trajectory band.

- [ ] **Step 1: Write the notebook**

```bash
python - <<'PY'
import json
from pathlib import Path

cells = [
    {
        "cell_type": "markdown",
        "source": [
            "# 06 — Scenario Simulator\n",
            "\n",
            "Interactive 'what-if' simulator. Move the sliders to set daily inputs, see the predicted weight + body-fat trajectories with 95% credible bands.\n",
            "\n",
            "Phase 1 caveat: parameters are drawn from population priors, so the bands will be wide. Phase 2 narrows them substantially by fitting `intake_bias` and `RMR_scale` to your data."
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import sys\n",
            "from pathlib import Path\n",
            "import matplotlib.pyplot as plt\n",
            "import numpy as np\n",
            "import pandas as pd\n",
            "from ipywidgets import interactive, FloatSlider, IntSlider, VBox, HBox\n",
            "\n",
            "REPO_ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n",
            "sys.path.insert(0, str(REPO_ROOT))\n",
            "\n",
            "from body_sim import simulate\n",
            "from body_sim.config import DEFAULT_PROFILE\n",
            "from body_sim.model import BodyState\n",
            "from body_sim.validation import _seed_state\n",
            "\n",
            "df = pd.read_parquet(REPO_ROOT / 'notebooks' / 'predictions' / 'daily_rollup.parquet')\n",
            "\n",
            "# Seed state from the most recent observed weight\n",
            "most_recent = df['weight_kg'].dropna().iloc[-1] if df['weight_kg'].notna().any() else 80.0\n",
            "initial_state = _seed_state(float(most_recent))\n",
            "print(f'Initial state: weight={initial_state.fat_mass_kg + initial_state.lean_mass_kg:.1f} kg, '\n",
            "      f'fat={initial_state.fat_mass_kg:.1f} kg, lean={initial_state.lean_mass_kg:.1f} kg')"
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "def render(intake_kcal, protein_g, carb_g, fat_g, sodium_mg, steps, vigorous_min, horizon_days):\n",
            "    inputs_per_day = [\n",
            "        {\n",
            "            'intake_kcal': intake_kcal,\n",
            "            'protein_g': protein_g,\n",
            "            'carb_g': carb_g,\n",
            "            'fat_g': fat_g,\n",
            "            'sodium_mg': sodium_mg,\n",
            "            'ee_hr_keytel_kcal': 0.0,  # rely on fallback (steps) for scenario sim\n",
            "            'workout_kcal': 0.0,\n",
            "            'vigorous_min': vigorous_min,\n",
            "            'intake_logged': True,\n",
            "            'hr_coverage_pct': 0.0,\n",
            "            'steps': steps,\n",
            "        }\n",
            "        for _ in range(horizon_days)\n",
            "    ]\n",
            "    samples = simulate.sample_parameters(n=200, seed=42)\n",
            "    result = simulate.simulate_forward(\n",
            "        initial_state=initial_state,\n",
            "        inputs_per_day=inputs_per_day,\n",
            "        profile=DEFAULT_PROFILE,\n",
            "        parameter_samples=samples,\n",
            "    )\n",
            "    weight_band = simulate.credible_band(result.predicted_weight_kg)\n",
            "    bf_band = simulate.credible_band(result.body_fat_pct)\n",
            "\n",
            "    fig, axes = plt.subplots(1, 2, figsize=(14, 5))\n",
            "    days = np.arange(1, horizon_days + 1)\n",
            "    axes[0].fill_between(days, weight_band['lo'], weight_band['hi'], alpha=0.25, label='95% band')\n",
            "    axes[0].plot(days, weight_band['median'], linewidth=2, label='Median')\n",
            "    axes[0].set_xlabel('Day')\n",
            "    axes[0].set_ylabel('Weight (kg)')\n",
            "    axes[0].set_title(f'Weight after {horizon_days} days')\n",
            "    axes[0].legend()\n",
            "    axes[0].grid(alpha=0.3)\n",
            "\n",
            "    axes[1].fill_between(days, bf_band['lo'], bf_band['hi'], alpha=0.25)\n",
            "    axes[1].plot(days, bf_band['median'], linewidth=2)\n",
            "    axes[1].set_xlabel('Day')\n",
            "    axes[1].set_ylabel('Body fat (%)')\n",
            "    axes[1].set_title('Body fat trajectory')\n",
            "    axes[1].grid(alpha=0.3)\n",
            "    plt.tight_layout()\n",
            "    plt.show()\n",
            "\n",
            "    print(f'Predicted weight at day {horizon_days}: {weight_band[\"median\"][-1]:.2f} kg '\n",
            "          f'(95% CI: {weight_band[\"lo\"][-1]:.2f}–{weight_band[\"hi\"][-1]:.2f})')\n",
            "    print(f'Predicted body fat at day {horizon_days}: {bf_band[\"median\"][-1]:.2f} % '\n",
            "          f'(95% CI: {bf_band[\"lo\"][-1]:.2f}–{bf_band[\"hi\"][-1]:.2f})')\n",
            "    delta_w = weight_band['median'][-1] - weight_band['median'][0]\n",
            "    print(f'Net weight change: {delta_w:+.2f} kg')\n",
            "\n",
            "interactive(\n",
            "    render,\n",
            "    intake_kcal=FloatSlider(min=1200, max=3500, step=50, value=2000, description='kcal/day'),\n",
            "    protein_g=FloatSlider(min=40, max=250, step=10, value=120, description='protein g'),\n",
            "    carb_g=FloatSlider(min=50, max=400, step=10, value=200, description='carb g'),\n",
            "    fat_g=FloatSlider(min=20, max=200, step=5, value=70, description='fat g'),\n",
            "    sodium_mg=FloatSlider(min=1000, max=6000, step=100, value=2300, description='sodium mg'),\n",
            "    steps=IntSlider(min=2000, max=20000, step=500, value=8000, description='steps'),\n",
            "    vigorous_min=IntSlider(min=0, max=120, step=5, value=15, description='vigorous min'),\n",
            "    horizon_days=IntSlider(min=7, max=180, step=7, value=56, description='horizon days'),\n",
            ")"
        ],
    },
]

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

Path('notebooks/06_scenario_simulator.ipynb').write_text(json.dumps(nb, indent=1))
print("Wrote notebooks/06_scenario_simulator.ipynb")
PY
```

- [ ] **Step 2: Execute to verify it runs (widgets won't render headless, but the code should not error)**

```bash
jupyter nbconvert --to notebook --execute notebooks/06_scenario_simulator.ipynb \
    --output 06_scenario_simulator.ipynb --ExecutePreprocessor.timeout=300
```

Expected: completes without errors. The widget container renders; sliders only animate in a live Jupyter session.

- [ ] **Step 3: Commit**

```bash
git add notebooks/06_scenario_simulator.ipynb
git commit -m "feat(body_sim): notebook 06 — interactive scenario simulator with ipywidgets"
```

---

## Task 23: Notebook 07 — live forecast tracking scaffold

**Files:**
- Create: `notebooks/07_live_tracking.ipynb`

Logs a forecast for the coming week to `notebooks/predictions/<date>.jsonl`. Phase 1 deliverable is the scaffold; Phase 2 will add the "score last week's forecast" step.

- [ ] **Step 1: Write the notebook**

```bash
python - <<'PY'
import json
from pathlib import Path

cells = [
    {
        "cell_type": "markdown",
        "source": [
            "# 07 — Live Forecast Tracking\n",
            "\n",
            "Logs the model's forecast for the coming week. Phase 2 will add the 'score last week's forecast vs observed' step.\n",
            "\n",
            "Run this once per week (e.g. every Sunday). The output JSONL grows over time and feeds Phase 2's retrospective."
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import datetime\n",
            "import json\n",
            "import sys\n",
            "from pathlib import Path\n",
            "import numpy as np\n",
            "import pandas as pd\n",
            "\n",
            "REPO_ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n",
            "sys.path.insert(0, str(REPO_ROOT))\n",
            "\n",
            "from body_sim import simulate\n",
            "from body_sim.config import DEFAULT_PROFILE\n",
            "from body_sim.validation import _seed_state\n",
            "\n",
            "df = pd.read_parquet(REPO_ROOT / 'notebooks' / 'predictions' / 'daily_rollup.parquet')\n",
            "today = datetime.date.today()\n",
            "horizon = 7"
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "# Use the trailing 14-day average of inputs as the 'expected' continued behaviour\n",
            "recent = df.tail(14)\n",
            "expected = {\n",
            "    'intake_kcal': float(recent['intake_kcal'].mean()),\n",
            "    'protein_g': float(recent['protein_g'].mean()),\n",
            "    'carb_g': float(recent['carb_g'].mean()),\n",
            "    'fat_g': float(recent['fat_g'].mean()),\n",
            "    'sodium_mg': float(recent['sodium_mg'].mean()),\n",
            "    'ee_hr_keytel_kcal': float(recent['ee_hr_keytel_kcal'].mean()),\n",
            "    'workout_kcal': float(recent['workout_kcal'].mean()),\n",
            "    'vigorous_min': int(recent['vigorous_min'].mean()),\n",
            "    'intake_logged': True,\n",
            "    'hr_coverage_pct': float(recent['hr_coverage_pct'].mean()),\n",
            "    'steps': int(recent['steps'].mean()),\n",
            "}\n",
            "expected"
        ],
    },
    {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "initial_state = _seed_state(float(df['weight_kg'].dropna().iloc[-1]))\n",
            "samples = simulate.sample_parameters(n=200, seed=int(today.toordinal()))\n",
            "result = simulate.simulate_forward(\n",
            "    initial_state=initial_state,\n",
            "    inputs_per_day=[expected.copy() for _ in range(horizon)],\n",
            "    profile=DEFAULT_PROFILE,\n",
            "    parameter_samples=samples,\n",
            ")\n",
            "band = simulate.credible_band(result.predicted_weight_kg)\n",
            "\n",
            "forecast_records = []\n",
            "for d_offset in range(horizon):\n",
            "    forecast_records.append({\n",
            "        'forecast_made_on': today.isoformat(),\n",
            "        'target_date': (today + datetime.timedelta(days=d_offset + 1)).isoformat(),\n",
            "        'predicted_weight_kg_lo': float(band['lo'][d_offset]),\n",
            "        'predicted_weight_kg_median': float(band['median'][d_offset]),\n",
            "        'predicted_weight_kg_hi': float(band['hi'][d_offset]),\n",
            "        'inputs_used': expected,\n",
            "        'phase': 1,\n",
            "    })\n",
            "\n",
            "out_path = REPO_ROOT / 'notebooks' / 'predictions' / 'live_forecasts.jsonl'\n",
            "with out_path.open('a') as f:\n",
            "    for rec in forecast_records:\n",
            "        f.write(json.dumps(rec) + '\\n')\n",
            "print(f'Wrote {len(forecast_records)} forecast records to {out_path}')\n",
            "print(f'Day +7 predicted weight: {band[\"median\"][-1]:.2f} kg '\n",
            "      f'(95% CI: {band[\"lo\"][-1]:.2f}–{band[\"hi\"][-1]:.2f})')"
        ],
    },
]

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

Path('notebooks/07_live_tracking.ipynb').write_text(json.dumps(nb, indent=1))
print("Wrote notebooks/07_live_tracking.ipynb")
PY
```

- [ ] **Step 2: Execute to verify**

```bash
jupyter nbconvert --to notebook --execute notebooks/07_live_tracking.ipynb \
    --output 07_live_tracking.ipynb --ExecutePreprocessor.timeout=300
```

Expected: completes; a `notebooks/predictions/live_forecasts.jsonl` file appears.

- [ ] **Step 3: Commit**

```bash
git add notebooks/07_live_tracking.ipynb notebooks/predictions/live_forecasts.jsonl
git commit -m "feat(body_sim): notebook 07 — weekly live forecast tracking scaffold"
```

---

## Task 24: Wrap-up — update beads, README, and verify the full suite

**Files:**
- Modify: `README.md` (root — small section if exists, else skip)
- Verify: full test suite passes

- [ ] **Step 1: Run the full body_sim test suite to confirm no regressions**

```bash
pytest tests/body_sim/ -v
```

Expected: all tests pass. If anything is red, fix and re-commit before proceeding.

- [ ] **Step 2: Run the foodlog main test suite to confirm we didn't break it**

```bash
pytest tests/ -v --ignore=tests/body_sim/
```

Expected: existing foodlog tests still pass. We only added top-level files and a package; nothing imported from the old code should change behaviour.

- [ ] **Step 3: Mark `foodlog-jok` Phase 1 as in-progress in beads**

```bash
bd update foodlog-jok --status=in_progress
```

(We're in progress as of the first task; this is a retroactive but honest claim — the Phase 1 work itself is complete pending review.)

Alternatively, if you prefer to mark closure when all tasks above are merged, run:

```bash
bd close foodlog-jok --reason="Phase 1 pipeline + notebooks landed; validation metrics inform Phase 2 prioritization"
```

- [ ] **Step 4: If a top-level README exists, append a small pointer to the sub-project**

Check whether `README.md` exists at the repo root:

```bash
ls README.md 2>/dev/null && echo EXISTS || echo MISSING
```

If `EXISTS`, append:

```markdown

## Sub-projects

- **body_sim/** — body-composition scenario simulator (notebook-driven). See `body_sim/README.md` and `docs/superpowers/specs/2026-05-18-body-composition-simulator-design.md`.
```

If `MISSING`, skip this step.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(body_sim): close Phase 1 — pipeline + notebooks + validation"
```

---

## Self-review

I reviewed the spec against this plan section-by-section:

- **Daily-rollup table**: covered by Tasks 11-14 with column-by-column tests against synthetic data; assembly verified end-to-end in Task 14 against the expected column set.
- **Missingness conventions**: enforced in the rollup helpers (NaN-as-latent for intake/steps; 0-as-true-zero for workouts/vigorous_min; ffill-with-cap for RHR; never-impute for weight/bf%); tested in Tasks 11-13.
- **HR-Keytel integration with `hr_coverage_pct` confidence weight**: Task 3 (per-min equation + daily integral + coverage helper), Task 10 (model uses coverage threshold to choose Keytel vs fallback), Task 12 (pipeline computes from interval_heart_rate).
- **Macros (TEF, glycogen-water, sodium-water, protein-protection)**: Tasks 5, 6, 7, 8 — each with its own small module and tests.
- **Adaptive thermogenesis**: Task 9.
- **Hall single-day update**: Task 10 composes everything.
- **Forward-walking validation**: Task 16.
- **Three required plots**: Task 18 + notebook 04 (Task 21).
- **Phase 1 passing thresholds reported**: notebook 04 (Task 21) prints PASS/FAIL against the thresholds defined in the spec.
- **`ipywidgets` scenario simulator**: notebook 06 (Task 22).
- **Live tracking scaffold**: notebook 07 (Task 23).
- **No PyMC at Phase 1**: confirmed — `parameter_samples` come from `np.random` (Task 15), not from a fitted posterior.
- **Spec path reconciliation (src/body_sim → body_sim)**: Task 1 step 6.

**Placeholder scan:** none — every step contains the exact code or command to run.

**Type consistency:** function names line up across tasks (`step()`, `BodyState`, `simulate_forward()`, `forward_walk()`, `summary_report()`). `parameter_samples` is consistently the name of the dict-of-arrays across Tasks 15, 16, 22, 23.

**Identified gap fixed inline:** the spec's daily-rollup table lists `sleep_rem_h`, `sleep_deep_h`, `sleep_light_h`, `sleep_awake_h` — these depend on `foodlog-taq` landing first. I didn't add them to the Phase 1 pipeline; the column set in Task 14's test only requires what exists today. The pipeline will absorb these columns transparently when `foodlog-taq` ships (the rollup helper just reads more columns from `sleep_sessions`).
