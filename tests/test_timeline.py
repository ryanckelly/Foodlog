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
