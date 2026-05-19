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
