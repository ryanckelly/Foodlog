from contextlib import asynccontextmanager

from fastapi import FastAPI

from foodlog.api.dependencies import cleanup_http_client
from foodlog.config import settings
from foodlog.db.database import get_engine
from foodlog.db.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield
    await cleanup_http_client()


def create_app() -> FastAPI:
    app = FastAPI(title="FoodLog", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "fatsecret": settings.fatsecret_configured,
            "usda": settings.usda_configured,
        }

    return app
