# FoodLog Weight Card Tie-Break Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `_build_movement_context` so the dashboard's Weight card always renders when a weight reading exists, even when a body-fat row shares the same `measured_at`.

**Architecture:** Two-row bug — `BodyComposition` stores Google Health weight points and body-fat points as separate rows. A barefoot Renpho weigh-in produces both at the same `measured_at`. The current `ORDER BY measured_at DESC LIMIT 1` query has no tiebreaker, so SQLite can return the body-fat row (which has `weight_kg=NULL`), and the dashboard's `if latest_body.weight_kg` check then drops the entire weight view. Fix: filter the "latest weight" query to `weight_kg IS NOT NULL`, then look up the body-fat row at the same `measured_at` separately. Same shape applies to the `week_ago` lookup.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, in-memory SQLite (existing test conftest pattern), Jinja2 templates.

**Bead:** `foodlog-bbl` — close on completion.

---

## File Structure

- `foodlog/api/routers/dashboard.py:184-199` — fix the `latest_body` and `week_ago` query block inside `_build_movement_context`. No new files; the change is localised to ~15 lines in one function.
- `tests/test_dashboard.py` — new regression test seeding two rows tied on `measured_at` and asserting the Weight card renders. Add alongside existing `test_feed_connected_renders_movement_section` so it shares fixtures.
- `doc/HEALTH_DATA.md` — strike the outdated "Renpho → Fitbit hop drops body fat" claim now that we have empirical evidence body fat does propagate when measured.

No file split needed — the fix is small and `_build_movement_context` is the right place for it (it already owns the weight view assembly).

---

### Task 1: Reproduce the bug in a failing test

**Files:**
- Modify: `tests/test_dashboard.py` (add new test alongside `test_feed_connected_renders_movement_section`)

- [ ] **Step 1: Add the regression test**

Append this test to `tests/test_dashboard.py`. It seeds two `BodyComposition` rows with the same `measured_at` — one weight-only, one body-fat-only — exactly mirroring the production data captured on 2026-05-04. The body-fat row is inserted first so SQLAlchemy's default tiebreaker (insertion order on a tied `ORDER BY`) returns it from `LIMIT 1`, reproducing the bug.

```python
def test_feed_renders_weight_card_when_body_fat_row_ties_measured_at(
    health_raw_client, db_session
):
    """Barefoot Renpho weigh-in produces two rows in body_composition with the
    same measured_at: one weight point (weight_kg set, body_fat_pct null) and
    one body-fat point (weight_kg null, body_fat_pct set). The dashboard's
    'latest body' query must return the weight row, not the body-fat row, or
    the Weight card silently disappears.

    Regression for foodlog-bbl. Live evidence captured 2026-05-05: 2026-05-04
    10:56:52 weigh-in produced both rows; the dashboard hid the weight card.
    """
    from foodlog.db.models import BodyComposition

    _login_health(health_raw_client)
    _seed_google_token(db_session)

    measured = datetime.datetime(2026, 5, 4, 10, 56, 52)

    # Insertion order matters — insert body-fat row FIRST so the buggy
    # `ORDER BY measured_at DESC LIMIT 1` (no tiebreaker) returns it.
    db_session.add(BodyComposition(
        external_id="users/x/dataTypes/body-fat/dataPoints/1",
        measured_at=measured,
        source="FITBIT_WEB_API",
        weight_kg=None,
        body_fat_pct=20.6,
    ))
    db_session.add(BodyComposition(
        external_id="users/x/dataTypes/weight/dataPoints/1",
        measured_at=measured,
        source="FITBIT_WEB_API",
        weight_kg=82.85,
        body_fat_pct=None,
    ))
    db_session.commit()
    _seed_recent_sync()

    resp = health_raw_client.get("/dashboard/feed?date_range=today")

    assert resp.status_code == 200
    # Card title and the weight value (in lbs, what the template renders).
    assert ">Weight</div>" in resp.text
    assert "182.7" in resp.text  # 82.85 kg → 182.69 lbs, formatted "%.1f"
    # Body fat from the sibling row should still appear on the same card.
    assert "body fat 20.6%" in resp.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_dashboard.py::test_feed_renders_weight_card_when_body_fat_row_ties_measured_at -v`

Expected: FAIL. The assertion `assert ">Weight</div>" in resp.text` will fail because `weight_view` is `None` and the `{% if weight %}` block in `movement_partial.html` is skipped.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_dashboard.py
git commit -m "test(dashboard): reproduce weight-card disappearance on barefoot weigh-in (foodlog-bbl)"
```

---

### Task 2: Fix `_build_movement_context` weight queries

**Files:**
- Modify: `foodlog/api/routers/dashboard.py:184-199`

- [ ] **Step 1: Replace the weight block in `_build_movement_context`**

Open `foodlog/api/routers/dashboard.py`. Locate the existing block (currently lines 184–199):

```python
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
```

Replace it with:

```python
    # `body_composition` holds Google Health weight points and body-fat points
    # as separate rows (different external_id, same measured_at on a barefoot
    # Renpho weigh-in). Filter to weight rows so a tied body-fat row can't
    # outrank the actual weight reading and silently hide the card. Then look
    # up the body-fat row at the same instant to keep the % on the card.
    latest_body = (db.query(BodyComposition)
                     .filter(BodyComposition.weight_kg.isnot(None))
                     .order_by(BodyComposition.measured_at.desc()).first())
    weight_view = None
    if latest_body is not None:
        week_ago = (db.query(BodyComposition)
                      .filter(BodyComposition.weight_kg.isnot(None),
                              BodyComposition.measured_at <= latest_body.measured_at
                                                            - datetime.timedelta(days=7))
                      .order_by(BodyComposition.measured_at.desc()).first())
        delta = None
        if week_ago is not None:
            delta = latest_body.weight_kg - week_ago.weight_kg
        body_fat_pct = latest_body.body_fat_pct
        if body_fat_pct is None:
            sibling_fat = (db.query(BodyComposition)
                             .filter(BodyComposition.measured_at == latest_body.measured_at,
                                     BodyComposition.body_fat_pct.isnot(None))
                             .first())
            if sibling_fat is not None:
                body_fat_pct = sibling_fat.body_fat_pct
        weight_view = {
            "weight_kg": latest_body.weight_kg,
            "delta_kg": delta,
            "body_fat_pct": body_fat_pct,
        }
```

Three real changes:
1. `latest_body` query filters `weight_kg.isnot(None)` so only weight rows can win the `ORDER BY`.
2. Same filter on `week_ago` so a body-fat row at the boundary can't kill the weekly delta.
3. New sibling-row lookup: if the latest weight row has no body-fat, look for a body-fat row at the same `measured_at` and merge its percentage into the view.

The `if latest_body and latest_body.weight_kg` guard collapses to `if latest_body is not None` because the filter guarantees `weight_kg` is set whenever a row is returned.

- [ ] **Step 2: Run the regression test from Task 1**

Run: `pytest tests/test_dashboard.py::test_feed_renders_weight_card_when_body_fat_row_ties_measured_at -v`

Expected: PASS. Card renders, weight value `182.7` is in the body, body fat `20.6%` is in the body.

- [ ] **Step 3: Run the full dashboard test file**

Run: `pytest tests/test_dashboard.py tests/test_movement_render.py -v`

Expected: all tests pass. The pre-existing tests should be unaffected; the only behavioural change is which row wins the tied `ORDER BY`.

- [ ] **Step 4: Run the full suite**

Run: `pytest`

Expected: all tests pass. If any existing test seeded a body-fat-only row and expected the Weight card to render with `weight_kg=None`, it would break — but no such test exists (`grep -n weight_kg tests/` confirms only `test_movement_render.py:36` and the new test set `weight_kg`).

- [ ] **Step 5: Commit the fix**

```bash
git add foodlog/api/routers/dashboard.py
git commit -m "fix(dashboard): filter latest_body to weight rows so body-fat ties don't hide the card

Two BodyComposition rows can share measured_at (weight + body-fat from a
barefoot Renpho weigh-in). The bare 'ORDER BY measured_at DESC LIMIT 1'
could return the body-fat row, whose weight_kg is null, so the Weight
card silently vanished. Filter on weight_kg IS NOT NULL, then merge in
body_fat_pct from the sibling row at the same measured_at.

Closes foodlog-bbl."
```

---

### Task 3: Update HEALTH_DATA.md

**Files:**
- Modify: `doc/HEALTH_DATA.md` (two prose locations, see Step 1)

- [ ] **Step 1: Correct the body-fat propagation claim**

Open `doc/HEALTH_DATA.md`. Find the paragraph that contains:

> **Why body fat shows up in the schema but never has data:** Renpho's own FAQ states *"When using third-party apps between platforms and the Renpho app, it only brings over Weight, Change and BMI. Other metrics like body fat% are not transferred over."* The Renpho → Fitbit hop drops body fat. Confirmed empirically 2026-05-02 — fresh weigh-in produced 1 weight point, 0 body-fat points in Google.

Replace that paragraph with:

> **Body fat propagation is conditional on a barefoot weigh-in.** Empirical history:
> - 2026-05-02 (socks on): 1 weight point, 0 body-fat points in Google.
> - 2026-05-03 (socks on): 1 weight point, 0 body-fat points.
> - 2026-05-04 (barefoot): 1 weight point + 1 body-fat point, both at the same `measured_at`.
>
> The earlier conclusion that "the Renpho → Fitbit hop drops body fat" was wrong — what was actually happening is that the scale couldn't measure body composition through socks, so no body-fat sample was created upstream. When the user weighs in barefoot, body fat reaches Google Health and lands in the `body_composition` table as a *separate row* keyed on a different `external_id` but the same `physicalTime`. Renpho's own FAQ caveat about third-party apps still applies to less common metrics (BMR, visceral fat, etc.) — Fitbit only relays weight + body fat.

Find the second related sentence later in the file:

> **Recorded by Renpho but not reachable via Google Health at all:**
> Body fat %, BMI, lean body mass, skeletal muscle mass, bone mass, body water %, visceral fat, BMR, metabolic age, protein %, subcutaneous fat. These appear in Health Connect on the phone but are not exposed via the cloud REST API.

Edit it to remove "Body fat %, " from the list (since we now have empirical evidence it does propagate barefoot):

> **Recorded by Renpho but not reachable via Google Health at all:**
> BMI, lean body mass, skeletal muscle mass, bone mass, body water %, visceral fat, BMR, metabolic age, protein %, subcutaneous fat. These appear in Health Connect on the phone but are not exposed via the cloud REST API.

- [ ] **Step 2: Commit the doc update**

```bash
git add doc/HEALTH_DATA.md
git commit -m "docs(health): correct body-fat propagation note — depends on barefoot weigh-in, not Fitbit dropping it"
```

---

### Task 4: Close the bead and verify on the live dashboard

**Files:** none (operational).

- [ ] **Step 1: Rebuild the running container**

The fix is in Python code that the running container loaded at startup, so a rebuild is required for the live dashboard to pick it up.

Run: `docker compose build foodlog && docker compose up -d foodlog`

Expected: container rebuilds and comes back healthy.

- [ ] **Step 2: Verify the live dashboard now renders the card**

Run: `curl -s http://127.0.0.1:3474/healthz` — confirm 200.

Then load `https://foodlog.ryanckelly.ca/dashboard` in the browser. The Weight card should now show `182.7 lbs (82.85 kg) · body fat 20.6%`. (If you've since taken a newer weigh-in, the latest values will appear instead.)

- [ ] **Step 3: Close the bead**

Run: `bd close foodlog-bbl`

Expected: bead moves to closed.

- [ ] **Step 4: Push**

Per `CLAUDE.md` session-completion rules:

```bash
git pull --rebase
git push
git status  # MUST show "up to date with origin"
```

If the repo is local-only (no remote), `git push` will print "no upstream"; that is the documented state per the session-start hook ("No git remote configured. Issues are saved locally only."). Verify by running `git remote -v` — if it's empty, skip the push step and note it in handoff.
