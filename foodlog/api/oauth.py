import json
from html import escape

from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from foodlog.api.dependencies import get_session_factory_cached
from foodlog.services.oauth import FoodLogOAuthProvider, login_secret_matches

router = APIRouter()


def get_oauth_provider() -> FoodLogOAuthProvider:
    return FoodLogOAuthProvider(get_session_factory_cached())


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/oauth/consent", response_class=HTMLResponse)
def consent_page(request_id: str):
    provider = get_oauth_provider()
    pending = provider.get_pending_authorization(request_id)
    if pending is None:
        return HTMLResponse("Authorization request not found or expired", status_code=404)
    scopes = ", ".join(escape(scope) for scope in json.loads(pending.scopes_json))
    body = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Authorize FoodLog</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
  </head>
  <body>
    <main>
      <h1>Authorize FoodLog</h1>
      <p>Claude is requesting access to FoodLog.</p>
      <p>Scopes: {scopes}</p>
      <form method="post" action="/oauth/consent">
        <input type="hidden" name="request_id" value="{escape(request_id)}">
        <label>
          FoodLog secret
          <input name="login_secret" type="password" autocomplete="current-password" required>
        </label>
        <button type="submit">Authorize</button>
      </form>
    </main>
  </body>
</html>
"""
    return HTMLResponse(body)


@router.post("/oauth/consent")
async def approve_consent(request: Request):
    form = await request.form()
    request_id = str(form.get("request_id", ""))
    login_secret = str(form.get("login_secret", ""))
    if not login_secret_matches(login_secret):
        return JSONResponse({"detail": "Invalid FoodLog secret"}, status_code=401)
    provider = get_oauth_provider()
    try:
        callback_url = provider.approve_pending_authorization(request_id)
    except ValueError:
        return JSONResponse(
            {"detail": "Authorization request not found or expired"}, status_code=404
        )
    return RedirectResponse(callback_url, status_code=302)
