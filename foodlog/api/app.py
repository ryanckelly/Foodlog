import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl
from starlette.middleware.sessions import SessionMiddleware

from foodlog.api.dependencies import cleanup_http_client, get_session_factory_cached
from foodlog.config import settings
from foodlog.db.database import get_engine
from foodlog.db.models import Base
from foodlog.services.oauth import FOODLOG_SCOPES, FoodLogOAuthProvider, FoodLogTokenVerifier
from mcp_server.server import create_mcp_server

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    session_factory = get_session_factory_cached()
    oauth_provider = FoodLogOAuthProvider(session_factory)
    token_verifier = FoodLogTokenVerifier(session_factory)

    # Create the MCP server once per app instance so its session_manager is a
    # singleton scoped to this app (allows test isolation: each create_app()
    # call gets a fresh StreamableHTTPSessionManager that can be run() once).
    mcp = create_mcp_server(
        auth_server_provider=oauth_provider,
        token_verifier=token_verifier,
    )

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

    from foodlog.api.auth import OAuthResourceMiddleware

    app.add_middleware(OAuthResourceMiddleware)
    if not settings.foodlog_session_secret_key:
        logger.warning(
            "FOODLOG_SESSION_SECRET_KEY is not set; session cookies use an "
            "insecure fallback secret. Set this in production."
        )
    # Registered after OAuthResourceMiddleware so Starlette's reverse-order
    # middleware stacking makes SessionMiddleware the outer wrapper.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.foodlog_session_secret_key or "unsafe-default",
    )

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
    from foodlog.api.routers.dashboard import router as dashboard_router
    from foodlog.api.routers.sso import router as sso_router

    app.include_router(oauth_router)
    app.include_router(entries_router)
    app.include_router(summary_router)
    app.include_router(foods_router)
    app.include_router(dashboard_router)
    app.include_router(sso_router)

    app.router.routes.extend(
        create_auth_routes(
            provider=oauth_provider,
            issuer_url=AnyHttpUrl(settings.public_base_url),
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=list(FOODLOG_SCOPES),
                default_scopes=list(FOODLOG_SCOPES),
            ),
            revocation_options=RevocationOptions(enabled=True),
        )
    )

    mcp_app = mcp.streamable_http_app()
    for middleware in reversed(mcp_app.user_middleware):
        app.add_middleware(middleware.cls, *middleware.args, **middleware.kwargs)
    app.router.routes.extend(mcp_app.routes)

    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=settings.foodlog_host, port=settings.foodlog_port)
