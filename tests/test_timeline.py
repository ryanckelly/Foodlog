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
