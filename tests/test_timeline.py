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
