# FoodLog Google SSO Design

## Overview
Secure the FoodLog web dashboard by replacing the local-network-only restriction with Google Single Sign-On (SSO). The application will use `authlib` and FastAPI's `SessionMiddleware` to authenticate the user against Google and verify their email matches a configured authorized email address.

## Architecture

**Authentication Flow (Authlib + SessionMiddleware):**
1. **Unauthenticated Request:** A user visits `/dashboard`. The router checks `request.session.get("user")`. Since it's empty, the user is redirected to `/login`.
2. **Login Route (`/login`):** Initializes the Google OAuth client via `authlib` and redirects the user to Google's consent screen.
3. **Google Consent:** The user logs in to Google and authorizes the FoodLog application.
4. **Callback Route (`/auth/callback`):** Google redirects the user back to this route with an authorization code.
   - The route exchanges the code for an access token and fetches the user's profile (specifically the email).
   - It checks if the email exactly matches the `FOODLOG_AUTHORIZED_EMAIL` environment variable.
   - If it matches, it sets `request.session["user"] = email` and redirects to `/dashboard`.
   - If it does not match, it returns a 403 Forbidden.
5. **Authenticated Request:** The user visits `/dashboard`. `request.session.get("user")` is populated, so the dashboard renders.

**Dependencies:**
- `authlib`: For handling the standard OAuth 2.0 flow with Google.
- `itsdangerous`: Used under the hood by FastAPI's `SessionMiddleware` to securely sign the session cookie.
- `httpx`: Required by Authlib for making asynchronous HTTP requests.

## Security Considerations
- **Session Security:** `SessionMiddleware` signs the cookie cryptographically using `FOODLOG_SESSION_SECRET_KEY`. This prevents tampering. The cookie should be `HttpOnly` and `Secure` (in production).
- **Authorization vs. Authentication:** Google handles *authentication* (proving who the user is). FoodLog handles *authorization* by strictly checking the authenticated email against the single `authorized_email` in the configuration.
- **CSRF Protection:** `authlib` automatically handles the `state` parameter during the OAuth flow to prevent Cross-Site Request Forgery attacks.
- **Removal of IP Restrictions:** The `cf-connecting-ip` and `cf-ray` header checks in `OAuthResourceMiddleware` will be removed, allowing the dashboard to be safely accessed over the public Cloudflare Tunnel.

## Configuration Updates
The following new environment variables will be added to `.env` and `foodlog/config.py`:
- `GOOGLE_CLIENT_ID`: The OAuth 2.0 Client ID from Google Cloud Console.
- `GOOGLE_CLIENT_SECRET`: The OAuth 2.0 Client Secret.
- `FOODLOG_SESSION_SECRET_KEY`: A secure, random string for signing session cookies.
- `FOODLOG_AUTHORIZED_EMAIL`: The exact Google email address permitted to access the dashboard.
