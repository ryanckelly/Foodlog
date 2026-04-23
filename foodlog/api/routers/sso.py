from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse, RedirectResponse

from foodlog.config import settings

router = APIRouter(tags=["sso"])

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
        return HTMLResponse("SSO is not configured.", status_code=500)
    redirect_uri = f"{settings.public_base_url}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return HTMLResponse("Authentication failed.", status_code=401)

    userinfo = token.get("userinfo")
    if not userinfo or "email" not in userinfo:
        return HTMLResponse("Could not retrieve email from Google.", status_code=401)

    email = userinfo["email"]
    if email.lower() != settings.foodlog_authorized_email.lower():
        return HTMLResponse(f"Unauthorized: {email} is not permitted.", status_code=403)

    request.session["user"] = email
    return RedirectResponse(url="/dashboard")


@router.get("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/dashboard")
