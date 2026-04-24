from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from foodlog.api.dependencies import get_session_factory_cached
from foodlog.config import settings
from foodlog.services.oauth import FoodLogTokenVerifier

PUBLIC_EXACT_PATHS = {
    "/healthz",
    "/.well-known/oauth-authorization-server",
    "/authorize",
    "/token",
    "/register",
    "/revoke",
    "/oauth/consent",
    "/login",
    "/auth/callback",
    "/logout",
}
PUBLIC_PREFIX_PATHS = (
    "/.well-known/oauth-protected-resource",
    "/dashboard",
    "/health/connect",
    "/static",
    "/manifest.webmanifest",
    "/sw.js",
)


class OAuthResourceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path == "/mcp"
            or path in PUBLIC_EXACT_PATHS
            or path.startswith(PUBLIC_PREFIX_PATHS)
        ):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._unauthorized()

        verifier = FoodLogTokenVerifier(get_session_factory_cached())
        token = await verifier.verify_token(auth_header.removeprefix("Bearer ").strip())
        if token is None:
            return self._unauthorized()

        required_scope = "foodlog.read"
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            required_scope = "foodlog.write"
        if required_scope not in token.scopes:
            return JSONResponse({"detail": "Insufficient scope"}, status_code=403)

        request.state.oauth_token = token
        return await call_next(request)

    def _unauthorized(self):
        metadata_url = (
            f"{settings.public_base_url}/.well-known/oauth-protected-resource/mcp"
        )
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="foodlog", resource_metadata="{metadata_url}"'
                )
            },
        )
