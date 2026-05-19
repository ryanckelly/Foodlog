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


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:///") or url.startswith("sqlite+")


def get_engine(db_url: str | None = None):
    url = db_url or settings.database_url
    if _is_sqlite_url(url):
        db_path = url.split("///", 1)[1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, echo=False)
    if _is_sqlite_url(url):
        _configure_sqlite(engine)
    return engine


def get_session_factory(engine=None):
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine)


def ensure_columns(engine, table: str, columns: dict[str, str]) -> None:
    """Add missing columns to an existing SQLite table.

    SQLAlchemy's ``Base.metadata.create_all`` is no-op when a table already
    exists, so it never adds columns introduced by later schema changes. This
    helper closes that gap for nullable, no-default columns — which is the only
    shape SQLite's ``ALTER TABLE ADD COLUMN`` supports without rewriting the
    table. Call from the FastAPI lifespan after ``create_all`` for any table
    that has gained columns post-initial-deploy.

    Args:
        engine: SQLAlchemy engine bound to a SQLite database.
        table: Existing table name (no quoting needed).
        columns: ``{column_name: sqlite_type_decl}`` where the decl is the raw
            SQLite type, e.g. ``"INTEGER"``, ``"VARCHAR(64)"``, ``"BOOLEAN"``.
            Always nullable; never include ``NOT NULL`` or ``DEFAULT``.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        info = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        if not info:
            # Table doesn't exist yet — create_all will handle it on next call.
            return
        existing = {row[1] for row in info}  # row[1] is column name
        for col, decl in columns.items():
            if col in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {decl}"))
