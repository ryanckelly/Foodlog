import logging

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from starlette.responses import PlainTextResponse, RedirectResponse

from foodlog.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sso"])

# client_id / client_secret are captured at import time. Changing these settings
# at runtime requires reloading this module.
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/login")
async def login(request: Request):
    if not settings.google_sso_configured:
        return PlainTextResponse("SSO is not configured.", status_code=500)
    redirect_uri = f"{settings.public_base_url}/auth/callback"
    try:
        return await oauth.google.authorize_redirect(request, redirect_uri)
    except OAuthError:
        logger.exception("Google OAuth authorize_redirect failed")
        return PlainTextResponse(
            "Unable to contact Google for authentication.", status_code=502
        )


@router.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        logger.exception("Google OAuth token exchange failed")
        return PlainTextResponse("Authentication failed.", status_code=401)

    userinfo = token.get("userinfo")
    if not userinfo or "email" not in userinfo:
        return PlainTextResponse("Could not retrieve email from Google.", status_code=401)

    email = userinfo["email"]
    if email.lower() != settings.foodlog_authorized_email.lower():
        logger.warning("Rejected unauthorized Google SSO login attempt for %s", email)
        return PlainTextResponse("Unauthorized.", status_code=403)

    request.session["user"] = email
    return RedirectResponse(url="/dashboard")


@router.get("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/dashboard")
