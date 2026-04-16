from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from foodlog.config import settings


def get_engine(db_url: str | None = None):
    url = db_url or settings.database_url
    db_path = url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, echo=False)


def get_session_factory(engine=None):
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine)
