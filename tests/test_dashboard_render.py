"""Smoke test the editorial dashboard renders with seeded entries."""
import datetime
import pytest
from fastapi.testclient import TestClient

from foodlog.db.models import FoodEntry


@pytest.fixture
def seeded_entries(db_session):
    now = datetime.datetime.now()
    rows = [
        FoodEntry(food_name="Poached egg", quantity=2, unit="pcs",
                  calories=150, protein_g=12, carbs_g=1, fat_g=10,
                  meal_type="breakfast", source="manual", raw_input="manual",
                  logged_at=now.replace(hour=7, minute=40, second=0, microsecond=0)),
        FoodEntry(food_name="Sourdough toast", quantity=1, unit="slice",
                  calories=120, protein_g=4, carbs_g=22, fat_g=1,
                  meal_type="breakfast", source="manual", raw_input="manual",
                  logged_at=now.replace(hour=7, minute=41, second=0, microsecond=0)),
        FoodEntry(food_name="Grilled chicken salad", quantity=1, unit="bowl",
                  calories=480, protein_g=42, carbs_g=18, fat_g=22,
                  meal_type="lunch", source="manual", raw_input="manual",
                  logged_at=now.replace(hour=13, minute=5, second=0, microsecond=0)),
        FoodEntry(food_name="Dark chocolate", quantity=20, unit="g",
                  calories=110, protein_g=1, carbs_g=9, fat_g=8,
                  meal_type="snack", source="manual", raw_input="manual",
                  logged_at=now.replace(hour=16, minute=20, second=0, microsecond=0)),
    ]
    for r in rows:
        db_session.add(r)
    db_session.commit()
    return rows


def test_index_masthead_renders(raw_client: TestClient):
    r = raw_client.get("/dashboard")
    assert r.status_code == 200
    for m in ("Le Journal", "Gastronomique", "Vol. MMXXVI",
              "Fraunces", "Période", "segmented"):
        assert m in r.text, f"missing in index: {m}"


def test_feed_empty_state_renders(raw_client: TestClient):
    r = raw_client.get("/dashboard/feed?date_range=today")
    assert r.status_code == 200
    assert "no courses recorded" in r.text
    assert "Répartition des macros" in r.text


def test_feed_seeded_entries_render(raw_client: TestClient, seeded_entries):
    r = raw_client.get("/dashboard/feed?date_range=today")
    assert r.status_code == 200
    for m in ("Poached egg", "Grilled chicken salad", "Dark chocolate",
              "course-ordinal", "macro-bar", "Les courses",
              "Registre du jour", "Breakfast", "Lunch", "Snack"):
        assert m in r.text, f"missing in feed: {m}"

    # macro percentages should sum roughly to 100
    import re
    pcts = [int(x) for x in re.findall(r'(\d+)% of calories', r.text)]
    assert len(pcts) == 3
    assert 99 <= sum(pcts) <= 100


def test_feed_also_writes_preview(raw_client: TestClient, seeded_entries, tmp_path):
    """Write full page to tmp for human inspection when run locally."""
    idx = raw_client.get("/dashboard").text
    feed = raw_client.get("/dashboard/feed?date_range=today").text
    full = idx.replace(
        '<div id="dashboard-content">\n    <div class="loading">Mesurant</div>\n</div>',
        f'<div id="dashboard-content">{feed}</div>',
    )
    out = tmp_path / "dashboard_preview.html"
    out.write_text(full)
    assert out.exists() and out.stat().st_size > 5000
