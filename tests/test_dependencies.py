from sqlalchemy.orm import sessionmaker

from foodlog.api.dependencies import get_session_factory_cached


def test_session_factory_cached_returns_sessionmaker():
    factory = get_session_factory_cached()
    assert isinstance(factory, sessionmaker)


def test_session_factory_cached_is_singleton():
    first = get_session_factory_cached()
    second = get_session_factory_cached()
    assert first is second
