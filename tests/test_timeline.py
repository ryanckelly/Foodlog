import datetime

import pytest
from fastapi.testclient import TestClient


def test_timeline_returns_200_for_today(db_session):
    # The fixture in conftest.py already disables Google SSO so /dashboard/* is open in tests.
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline")
    assert r.status_code == 200
    # Stub assertion — refined in later tasks.
    assert "timeline" in r.text.lower()


def test_timeline_accepts_date_param(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert "2026" in r.text  # date is rendered somewhere


def test_timeline_renders_hr_panel_with_data(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalHeartRate

    # Seed three windows on 2026-04-12 between 12:00 and 12:30
    for hr_avg, m in [(110, 0), (115, 15), (108, 30)]:
        db_session.add(IntervalHeartRate(
            start_at=datetime.datetime(2026, 4, 12, 12, m, 0),
            bpm_avg=hr_avg, bpm_min=hr_avg - 20, bpm_max=hr_avg + 30,
            source="FITBIT",
        ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    # The partial uses class="hr-col" per slot with data
    assert r.text.count('class="hr-col"') == 3
    # Min and max BPM should be reflected somewhere in the markup
    assert 'data-bpm-avg="110"' in r.text


def test_timeline_renders_activity_panels(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalActivity

    db_session.add_all([
        IntervalActivity(
            start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
            steps=649, distance_m=420.268, floors=None, source="FITBIT",
        ),
        IntervalActivity(
            start_at=datetime.datetime(2026, 4, 12, 12, 15, 0),
            steps=1462, distance_m=1133.0, floors=5, source="FITBIT",
        ),
    ])
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert r.text.count('class="steps-col"') == 2
    assert r.text.count('class="dist-col"') == 2
    # Only one floors data point (the other has floors=None)
    assert r.text.count('class="floors-col"') == 1


def test_timeline_renders_azm_stacked_panel(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalAzm

    db_session.add(IntervalAzm(
        start_at=datetime.datetime(2026, 4, 12, 12, 35, 0),
        fat_burn_min=12, cardio_min=2, peak_min=None, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert 'class="azm-col"' in r.text
    assert 'azm-fat-burn' in r.text
    assert 'azm-cardio' in r.text


def test_timeline_overlays_workouts_and_meal_dots(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import Workout, FoodEntry

    db_session.add(Workout(
        external_id="walk-1",
        start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
        end_at=datetime.datetime(2026, 4, 12, 12, 47, 0),
        activity_type="Walk",
        duration_min=47,
        calories_kcal=300.0, distance_m=3500.0,
        avg_hr=112, max_hr=145, source="FITBIT",
    ))
    db_session.add(FoodEntry(
        meal_type="lunch", food_name="salad",
        quantity=1, unit="bowl",
        calories=400, protein_g=20, carbs_g=30, fat_g=10,
        source="manual", raw_input="salad",
        logged_at=datetime.datetime(2026, 4, 12, 13, 0, 0),
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert 'class="tl-workout-band"' in r.text
    assert 'Walk' in r.text
    assert 'class="tl-meal-dot' in r.text  # may have extra classes appended


def test_timeline_header_has_date_navigation(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    assert 'class="tl-nav-prev"' in r.text
    assert 'class="tl-nav-next"' in r.text
    # Today is shown only when not on today
    assert 'class="tl-nav-today"' in r.text
    # Date picker form
    assert 'name="date"' in r.text


def test_timeline_header_hides_today_when_on_today(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline")  # defaults to today
    assert 'class="tl-nav-today"' not in r.text


def test_timeline_focus_param_highlights_matching_workout(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import Workout

    db_session.add(Workout(
        external_id="walk-2",
        start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
        end_at=datetime.datetime(2026, 4, 12, 12, 47, 0),
        activity_type="Walk", duration_min=47,
        calories_kcal=300.0, distance_m=3500.0,
        avg_hr=112, max_hr=145, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())

    # Without focus → standard band, no focused class on the element
    r1 = client.get("/dashboard/timeline?date=2026-04-12")
    assert 'tl-workout-band' in r1.text
    # tl-workout-focused only appears in CSS; not as an applied class attribute
    assert 'class="tl-workout-band tl-workout-focused"' not in r1.text

    # With matching focus → focused class applied to element
    r2 = client.get("/dashboard/timeline?date=2026-04-12&focus=12:00-12:47")
    assert 'class="tl-workout-band tl-workout-focused"' in r2.text

    # With mismatched focus → focused class not applied
    r3 = client.get("/dashboard/timeline?date=2026-04-12&focus=09:00-10:00")
    assert 'class="tl-workout-band tl-workout-focused"' not in r3.text


def test_timeline_renders_landscape_pill_strip(db_session):
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalHeartRate

    # Seed data so has_data=True and the pill strip is rendered
    db_session.add(IntervalHeartRate(
        start_at=datetime.datetime(2026, 4, 12, 10, 0, 0),
        bpm_avg=100, bpm_min=80, bpm_max=120, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    # Pills have anchor links for hash routing; HR is default
    assert 'class="tl-pill"' in r.text
    assert 'href="#tl-hr"' in r.text
    assert 'href="#tl-steps"' in r.text
    assert 'href="#tl-azm"' in r.text


def test_timeline_empty_state_when_no_data(db_session):
    from foodlog.api.app import create_app
    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2024-01-01")
    assert r.status_code == 200
    assert "no data" in r.text.lower()
    # Charts should not render
    assert 'class="tl-chart"' not in r.text


def test_timeline_future_day_shows_empty_state(db_session):
    from foodlog.api.app import create_app
    future = datetime.date.today() + datetime.timedelta(days=2)
    client = TestClient(create_app())
    r = client.get(f"/dashboard/timeline?date={future.isoformat()}")
    assert r.status_code == 200
    assert "no data" in r.text.lower()


def test_timeline_stacks_overlapping_meal_dots(db_session):
    """Two meals at the same logged_at should render at distinct stack indices
    so each remains visually and click-targetable separately."""
    from foodlog.api.app import create_app
    from foodlog.db.models import FoodEntry

    same_ts = datetime.datetime(2026, 4, 12, 13, 0, 0)
    db_session.add(FoodEntry(
        meal_type="lunch", food_name="Beef Pho",
        quantity=1, unit="bowl",
        calories=400, protein_g=20, carbs_g=30, fat_g=10,
        source="manual", raw_input="pho", logged_at=same_ts,
    ))
    db_session.add(FoodEntry(
        meal_type="lunch", food_name="Beef Banh Mi",
        quantity=1, unit="sandwich",
        calories=500, protein_g=22, carbs_g=55, fat_g=15,
        source="manual", raw_input="banh mi", logged_at=same_ts,
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    # First dot at top:4px (stack 0), second at top:14px (stack 1). The closing
    # quote disambiguates from CSS rules that use `top: Npx;` instead.
    assert 'top: 4px"' in r.text
    assert 'top: 14px"' in r.text
    # Strip height grew from base 18px to 28px (one extra stack row).
    assert "--meal-strip-h: 28px" in r.text


def test_timeline_does_not_stack_distant_meals(db_session):
    """Meals well-separated horizontally should all sit on the same row (top:4px)."""
    from foodlog.api.app import create_app
    from foodlog.db.models import FoodEntry

    db_session.add(FoodEntry(
        meal_type="breakfast", food_name="Oatmeal",
        quantity=1, unit="bowl",
        calories=300, protein_g=10, carbs_g=50, fat_g=5,
        source="manual", raw_input="oats",
        logged_at=datetime.datetime(2026, 4, 12, 8, 0, 0),
    ))
    db_session.add(FoodEntry(
        meal_type="dinner", food_name="Pasta",
        quantity=1, unit="plate",
        calories=600, protein_g=20, carbs_g=80, fat_g=15,
        source="manual", raw_input="pasta",
        logged_at=datetime.datetime(2026, 4, 12, 19, 0, 0),
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    # Both dots should be on row 0 → inline style `top: 4px"` appears twice;
    # the stack-1 form `top: 14px"` should never appear (CSS rules using
    # `top: 14px;` for the tooltip are excluded by the trailing quote).
    assert r.text.count('top: 4px"') == 2
    assert 'top: 14px"' not in r.text
    # Strip stays at base height.
    assert "--meal-strip-h: 18px" in r.text


def test_timeline_renders_hr_gridline_labels(db_session):
    """HR chart should show fixed-range gridline labels in bpm regardless of data values."""
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalHeartRate

    db_session.add(IntervalHeartRate(
        start_at=datetime.datetime(2026, 4, 12, 10, 0, 0),
        bpm_avg=110, bpm_min=90, bpm_max=130, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    # 25/50/75/100% of the 40-180 range = 75/110/145/180 bpm
    for label in ("75 bpm", "110 bpm", "145 bpm", "180 bpm"):
        assert label in r.text
    # And the gridline overlay containers are present
    assert 'class="tl-gridlines"' in r.text
    assert 'class="tl-y-axis"' in r.text


def test_timeline_steps_gridline_labels_round_to_nearest_1k(db_session):
    """Steps gridline labels are quartiles of the peak rounded to the nearest 1,000."""
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalActivity

    # Peak = 8534 → quartiles 2133.5/4267/6400.5/8534 → round-to-1k 2000/4000/6000/9000
    db_session.add(IntervalActivity(
        start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
        steps=8534, distance_m=None, floors=None, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    # Render the y-axis labels exactly. Use specific surrounding markup so we
    # don't accidentally match e.g. the data-steps attribute.
    for label in (">2,000<", ">4,000<", ">6,000<", ">9,000<"):
        assert label in r.text


def test_timeline_renders_gridlines_per_chart(db_session):
    """Every rendered chart panel should embed the 3-line gridline overlay."""
    from foodlog.api.app import create_app
    from foodlog.db.models import IntervalHeartRate, IntervalActivity, IntervalAzm

    db_session.add(IntervalHeartRate(
        start_at=datetime.datetime(2026, 4, 12, 10, 0, 0),
        bpm_avg=110, bpm_min=90, bpm_max=130, source="FITBIT",
    ))
    db_session.add(IntervalActivity(
        start_at=datetime.datetime(2026, 4, 12, 12, 0, 0),
        steps=4000, distance_m=3000.0, floors=8, source="FITBIT",
    ))
    db_session.add(IntervalAzm(
        start_at=datetime.datetime(2026, 4, 12, 12, 35, 0),
        fat_burn_min=12, cardio_min=2, peak_min=2, source="FITBIT",
    ))
    db_session.commit()

    client = TestClient(create_app())
    r = client.get("/dashboard/timeline?date=2026-04-12")
    assert r.status_code == 200
    # 5 chart panels (HR/steps/distance/floors/azm) → 5 gridline overlays.
    assert r.text.count('class="tl-gridlines"') == 5
