from collections.abc import Generator

import httpx
from sqlalchemy.orm import Session

from foodlog.clients.fatsecret import FatSecretClient
from foodlog.clients.usda import USDAClient
from foodlog.config import settings
from foodlog.db.database import get_session_factory

_session_factory = None
_http_client: httpx.AsyncClient | None = None


def get_db() -> Generator[Session, None, None]:
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory()
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def get_session_factory_cached():
    """Return a cached sessionmaker. Used by MCP tools that open short-lived
    sessions directly, rather than going through FastAPI dependency injection."""
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory()
    return _session_factory


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


def get_fatsecret_client() -> FatSecretClient | None:
    if not settings.fatsecret_configured:
        return None
    return FatSecretClient(
        client_id=settings.fatsecret_consumer_key,
        client_secret=settings.fatsecret_consumer_secret,
        http_client=get_http_client(),
    )


def get_usda_client() -> USDAClient | None:
    if not settings.usda_configured:
        return None
    return USDAClient(
        api_key=settings.usda_api_key,
        http_client=get_http_client(),
    )


async def cleanup_http_client():
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
