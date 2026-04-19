from contextlib import asynccontextmanager

from fastapi import FastAPI

from foodlog.api.dependencies import cleanup_http_client
from foodlog.config import settings
from foodlog.db.database import get_engine
from foodlog.db.models import Base
from mcp_server.server import create_mcp_server


def create_app() -> FastAPI:
    # Create the MCP server once per app instance so its session_manager is a
    # singleton scoped to this app (allows test isolation: each create_app()
    # call gets a fresh StreamableHTTPSessionManager that can be run() once).
    mcp = create_mcp_server()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Initialize DB
        engine = get_engine()
        Base.metadata.create_all(engine)

        # Start MCP session manager (required for streamable_http_app to work)
        async with mcp.session_manager.run():
            yield

        await cleanup_http_client()

    app = FastAPI(title="FoodLog", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "fatsecret": settings.fatsecret_configured,
            "usda": settings.usda_configured,
        }

    from foodlog.api.routers.entries import router as entries_router
    from foodlog.api.routers.foods import router as foods_router
    from foodlog.api.routers.summary import router as summary_router
    from foodlog.api.oauth import router as oauth_router

    app.include_router(oauth_router)
    app.include_router(entries_router)
    app.include_router(summary_router)
    app.include_router(foods_router)

    # Mount MCP at /mcp (the inner Starlette app's route is "/" due to
    # streamable_http_path="/" in create_mcp_server).
    app.mount("/mcp", mcp.streamable_http_app())

    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=settings.foodlog_host, port=settings.foodlog_port)
