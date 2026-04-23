"""Google Health token storage and access-token minting.

The refresh token is encrypted at rest with Fernet and stored in the
singleton ``google_oauth_token`` row.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from foodlog.config import settings
from foodlog.db.models import GoogleOAuthToken

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class TokenMissing(Exception):
    """Raised when no Google refresh token is stored."""


class TokenInvalid(Exception):
    """Raised when Google rejects the refresh token (invalid_grant)."""


@dataclass(slots=True)
class AccessToken:
    value: str
    expires_in: int


TokenAgeDays = float


class GoogleTokenService:
    def __init__(self, db: Session):
        self._db = db
        if not settings.foodlog_google_token_key:
            raise RuntimeError("FOODLOG_GOOGLE_TOKEN_KEY is not configured")
        self._fernet = Fernet(settings.foodlog_google_token_key.encode())

    # ---------- storage ----------

    def save_refresh_token(
        self,
        refresh_token: str,
        scopes: list[str],
        issued_at: datetime.datetime,
    ) -> None:
        ciphertext = self._fernet.encrypt(refresh_token.encode()).decode()
        row = self._db.get(GoogleOAuthToken, 1)
        if row is None:
            row = GoogleOAuthToken(
                id=1,
                refresh_token_encrypted=ciphertext,
                scopes_json=json.dumps(scopes),
                issued_at=issued_at,
            )
            self._db.add(row)
        else:
            row.refresh_token_encrypted = ciphertext
            row.scopes_json = json.dumps(scopes)
            row.issued_at = issued_at
        self._db.commit()

    def load_refresh_token(self) -> str:
        row = self._db.get(GoogleOAuthToken, 1)
        if row is None:
            raise TokenMissing()
        try:
            return self._fernet.decrypt(row.refresh_token_encrypted.encode()).decode()
        except InvalidToken as e:
            raise TokenInvalid("refresh token ciphertext could not be decrypted") from e

    def token_age_days(self) -> TokenAgeDays:
        row = self._db.get(GoogleOAuthToken, 1)
        if row is None:
            raise TokenMissing()
        delta = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - row.issued_at
        return delta.total_seconds() / 86400.0

    def forget(self) -> None:
        row = self._db.get(GoogleOAuthToken, 1)
        if row is not None:
            self._db.delete(row)
            self._db.commit()

    # ---------- access-token minting ----------

    async def mint_access_token(self, http: httpx.AsyncClient) -> AccessToken:
        refresh = self.load_refresh_token()
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code == 400:
            body = resp.json()
            if body.get("error") == "invalid_grant":
                raise TokenInvalid(body.get("error_description", "invalid_grant"))
        resp.raise_for_status()
        data = resp.json()
        row = self._db.get(GoogleOAuthToken, 1)
        if row is not None:
            row.last_used_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            self._db.commit()
        return AccessToken(value=data["access_token"], expires_in=int(data["expires_in"]))
