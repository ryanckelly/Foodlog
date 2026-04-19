import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from foodlog.api.app import create_app
from foodlog.api.dependencies import get_db, reset_session_factory_for_tests
from foodlog.config import settings
from foodlog.db.models import Base, OAuthAccessToken
from foodlog.services.oauth import hash_token

TEST_ACCESS_TOKEN = "test-access-token"


@pytest.fixture(autouse=True)
def _oauth_settings(monkeypatch):
    monkeypatch.setattr(settings, "foodlog_public_base_url", "https://foodlog.example.com")
    monkeypatch.setattr(settings, "foodlog_oauth_login_secret", "test-login-secret")


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    reset_session_factory_for_tests(SessionLocal)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        reset_session_factory_for_tests(None)


@pytest.fixture
def oauth_token(db_session):
    db_session.add(
        OAuthAccessToken(
            token_hash=hash_token(TEST_ACCESS_TOKEN),
            client_id="pytest-client",
            scopes_json='["foodlog.read","foodlog.write"]',
            resource=settings.public_mcp_resource_url,
            expires_at=int(datetime.datetime.now(datetime.UTC).timestamp()) + 3600,
        )
    )
    db_session.commit()
    return TEST_ACCESS_TOKEN


@pytest.fixture
def raw_client(db_session):
    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(raw_client, oauth_token):
    raw_client.headers.update({"Authorization": f"Bearer {oauth_token}"})
    yield raw_client
