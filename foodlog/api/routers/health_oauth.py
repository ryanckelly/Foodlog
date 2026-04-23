"""Google Health OAuth routes: /health/connect and /health/connect/callback.

Guarded by the SSO session: only an SSO-authenticated authorized_email
can initiate or complete the flow. The refresh token returned by Google
is encrypted (Fernet) and written to the singleton google_oauth_token
row.
"""
from __future__ import annotations

import base64
import datetime
import json
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from foodlog.api.dependencies import get_db
from foodlog.config import settings
from foodlog.services.google_token import GoogleTokenService

router = APIRouter(tags=["health-oauth"])

HEALTH_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
]

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _require_sso_session(request: Request) -> str | None:
    """Return None if authorized, otherwise a redirect path."""
    user = request.session.get("user")
    if user != settings.foodlog_authorized_email:
        return "/login"
    return None


def _decode_id_token_email(id_token: str) -> str | None:
    try:
        _, payload_b64, _ = id_token.split(".")
        # base64 urlsafe, pad
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("email")
    except Exception:
        return None


async def _exchange_code(code: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        email = _decode_id_token_email(data.get("id_token", ""))
        data["id_token_email"] = email
        return data


@router.get("/health/connect")
def connect(request: Request):
    redirect = _require_sso_session(request)
    if redirect:
        return RedirectResponse(redirect, status_code=302)

    state = secrets.token_urlsafe(32)
    request.session["health_oauth_state"] = state
    redirect_uri = f"{settings.public_base_url}/health/connect/callback"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(HEALTH_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "state": state,
    }
    # On initial connect, force the consent screen so Google returns a
    # refresh token. On opportunistic re-auth we may later omit this.
    if request.query_params.get("force_consent") != "false":
        params["prompt"] = "consent"
    url = f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"
    return RedirectResponse(url, status_code=302)


@router.get("/health/connect/callback")
async def callback(request: Request, db: Session = Depends(get_db)):
    redirect = _require_sso_session(request)
    if redirect:
        return RedirectResponse(redirect, status_code=302)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    stored_state = request.session.get("health_oauth_state")
    if not code or not state or state != stored_state:
        raise HTTPException(status_code=400, detail="invalid oauth state")

    redirect_uri = f"{settings.public_base_url}/health/connect/callback"
    token = await _exchange_code(code, redirect_uri)

    email = token.get("id_token_email")
    if email is None or email.lower() != settings.foodlog_authorized_email.lower():
        raise HTTPException(
            status_code=403,
            detail=f"email {email!r} is not the authorized user",
        )

    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token. Remove the app from "
                   "https://myaccount.google.com/permissions and reconnect.",
        )

    svc = GoogleTokenService(db)
    svc.save_refresh_token(
        refresh_token=refresh_token,
        scopes=token.get("scope", "").split(),
        issued_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    )

    # Drop the state so the URL can't be replayed.
    request.session.pop("health_oauth_state", None)

    return RedirectResponse("/dashboard", status_code=302)
