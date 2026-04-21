# FoodLog Google SSO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Secure the web dashboard by replacing the local-network restriction with Google Single Sign-On (SSO) using `authlib` and FastAPI session cookies.

**Architecture:** Use `authlib` to handle the standard OAuth 2.0 flow with Google. Replace the Cloudflare IP check in `OAuthResourceMiddleware` with FastAPI's built-in `SessionMiddleware`. Add `/login` and `/auth/callback` routes. In the callback, verify the authenticated Google email matches a configured `authorized_email` before issuing a session cookie.

**Tech Stack:** FastAPI, `authlib`, `itsdangerous`, `httpx`

---

### Task 1: Install Dependencies and Update Configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `foodlog/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add new dependencies to `pyproject.toml`**

Add `authlib`, `itsdangerous`, and `httpx` to the `dependencies` list. (Ensure you keep the existing dependencies intact).

- [ ] **Step 2: Add SSO configuration to `Settings` in `foodlog/config.py`**

```python
class Settings(BaseSettings):
    # ... existing fields ...
    google_client_id: str = ""
    google_client_secret: str = ""
    session_secret_key: str = ""
    authorized_email: str = ""
    
    @property
    def google_sso_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.session_secret_key and self.authorized_email)
```

- [ ] **Step 3: Add new configuration keys to `.env.example`**

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
FOODLOG_SESSION_SECRET_KEY=
FOODLOG_AUTHORIZED_EMAIL=
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml foodlog/config.py .env.example
git commit -m "feat(auth): add authlib dependencies and sso configuration"
```

### Task 2: Setup Session Middleware and Remove IP Restriction

**Files:**
- Modify: `foodlog/api/app.py`
- Modify: `foodlog/api/auth.py`

- [ ] **Step 1: Add `SessionMiddleware` to `foodlog/api/app.py`**

Import `SessionMiddleware` from `starlette.middleware.sessions`. Add it to the FastAPI app instance, passing `settings.session_secret_key` as the `secret_key`. Do this *before* `OAuthResourceMiddleware`.

```python
from starlette.middleware.sessions import SessionMiddleware
from foodlog.config import settings

# ... near app = FastAPI(...)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key or "unsafe-default")
```

- [ ] **Step 2: Remove the Cloudflare IP check from `OAuthResourceMiddleware`**

In `foodlog/api/auth.py`, locate this block and remove it entirely, allowing `/dashboard` routes to pass through this middleware cleanly:

```python
        if path.startswith("/dashboard"):
            if "cf-connecting-ip" in request.headers or "cf-ray" in request.headers:
                return JSONResponse(
                    {"detail": "Dashboard is restricted to local network access only."},
                    status_code=403,
                )
            return await call_next(request)
```

*(Note: We will secure `/dashboard` in the router itself in the next task).*

- [ ] **Step 3: Commit**

```bash
git add foodlog/api/app.py foodlog/api/auth.py
git commit -m "refactor(auth): remove local ip restriction and add session middleware"
```

### Task 3: Create the SSO Router

**Files:**
- Create: `foodlog/api/routers/sso.py`
- Modify: `foodlog/api/app.py`

- [ ] **Step 1: Create the SSO router with `authlib`**

Create `foodlog/api/routers/sso.py`. 

```python
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
    if email.lower() != settings.authorized_email.lower():
        return HTMLResponse(f"Unauthorized: {email} is not permitted.", status_code=403)
        
    request.session["user"] = email
    return RedirectResponse(url="/dashboard")

@router.get("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/dashboard")
```

- [ ] **Step 2: Include the SSO router in the main app**

In `foodlog/api/app.py`, import the new router and include it:

```python
from foodlog.api.routers import sso
# ...
app.include_router(sso.router)
```

- [ ] **Step 3: Commit**

```bash
git add foodlog/api/routers/sso.py foodlog/api/app.py
git commit -m "feat(auth): implement google sso login and callback routes"
```

### Task 4: Secure the Dashboard Routes

**Files:**
- Modify: `foodlog/api/routers/dashboard.py`
- Modify: `tests/test_dashboard.py`
- Modify: `tests/test_dashboard_render.py`

- [ ] **Step 1: Require session for Dashboard index**

In `foodlog/api/routers/dashboard.py`, modify the `index` function to check the session. If `user` is not in `request.session` AND SSO is configured, redirect to `/login`. If SSO is *not* configured, allow access (for local dev fallback).

```python
from starlette.responses import RedirectResponse
from foodlog.config import settings

@router.get("", response_class=HTMLResponse)
def index(request: Request):
    if settings.google_sso_configured and "user" not in request.session:
        return RedirectResponse(url="/login")
        
    return templates.TemplateResponse(
# ... rest of function ...
```

- [ ] **Step 2: Require session for Dashboard feed**

Do the same for `feed_partial`:

```python
@router.get("/feed", response_class=HTMLResponse)
def feed_partial(
    request: Request,
    date_range: str = "today",
    db: Session = Depends(get_db),
):
    if settings.google_sso_configured and "user" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
# ... rest of function ...
```

- [ ] **Step 3: Update tests to mock SSO configuration**

Since the dashboard tests now run in an environment where SSO might not be configured (or might need to be mocked), ensure `test_dashboard.py` and `test_dashboard_render.py` still pass. You can either mock `settings.google_sso_configured` to `False` during tests or add the session data to the `TestClient` request.

Example for `tests/test_dashboard.py`:
```python
from unittest.mock import patch

@patch("foodlog.api.routers.dashboard.settings.google_sso_configured", False)
def test_dashboard_index(client: TestClient):
    response = client.get("/dashboard")
    assert response.status_code == 200
```
*(Apply similar patches to `test_dashboard_render.py` as needed).*

- [ ] **Step 4: Run tests to verify**

Run: `pytest tests/test_dashboard.py tests/test_dashboard_render.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add foodlog/api/routers/dashboard.py tests/test_dashboard.py tests/test_dashboard_render.py
git commit -m "feat(auth): secure dashboard routes behind session check"
```
