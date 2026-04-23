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
