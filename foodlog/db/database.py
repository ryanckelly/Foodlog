from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from foodlog.config import settings


def _configure_sqlite(engine: Engine) -> None:
    """Enable safer SQLite behavior for app + local dashboard readers."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_engine(db_url: str | None = None):
    url = db_url or settings.database_url
    db_path = url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, echo=False)
    if url.startswith("sqlite:///"):
        _configure_sqlite(engine)
    return engine


def get_session_factory(engine=None):
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine)
