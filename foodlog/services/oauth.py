import datetime
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    TokenVerifier,
)
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyHttpUrl, AnyUrl
from sqlalchemy.orm import Session

from foodlog.config import settings
from foodlog.db.models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthPendingAuthorization,
    OAuthRefreshToken,
)

FOODLOG_SCOPES = ("foodlog.read", "foodlog.write")
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def now_epoch() -> int:
    return int(time.time())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json_list(values: Sequence[str] | None) -> str:
    return json.dumps(list(values or []), separators=(",", ":"))


def _load_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    loaded = json.loads(value)
    return [str(item) for item in loaded]


def _new_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def _append_query(url: str, values: dict[str, str | None]) -> str:
    split = urlsplit(url)
    query = parse_qsl(split.query, keep_blank_values=True)
    query.extend((key, value) for key, value in values.items() if value is not None)
    return urlunsplit(
        (split.scheme, split.netloc, split.path, urlencode(query), split.fragment)
    )


def _redirect_uri_allowed(uri: str) -> bool:
    if uri == CLAUDE_CALLBACK:
        return True

    split = urlsplit(uri)
    if split.scheme == "https" and split.netloc:
        return True

    if split.scheme != "http" or split.path != "/callback":
        return False
    if split.hostname not in {"localhost", "127.0.0.1"}:
        return False
    try:
        return split.port is not None
    except ValueError:
        return False


def _loopback_callbacks_match(registered_uri: str, requested_uri: str) -> bool:
    registered = urlsplit(registered_uri)
    requested = urlsplit(requested_uri)

    if registered.scheme != "http" or requested.scheme != "http":
        return False
    if registered.hostname not in {"localhost", "127.0.0.1"}:
        return False
    if requested.hostname != registered.hostname:
        return False
    if registered.path != "/callback" or requested.path != registered.path:
        return False
    if registered.query != requested.query or registered.fragment != requested.fragment:
        return False

    try:
        return registered.port is not None and requested.port is not None
    except ValueError:
        return False


def _client_registered_scopes(client: OAuthClientInformationFull) -> list[str]:
    return client.scope.split() if client.scope else list(FOODLOG_SCOPES)


def _requested_scopes(
    scopes: list[str] | None, client: OAuthClientInformationFull
) -> list[str]:
    if scopes is None:
        return _client_registered_scopes(client)
    return scopes


def _validate_scopes_for_authorize(
    scopes: list[str], client: OAuthClientInformationFull
) -> None:
    invalid = [scope for scope in scopes if scope not in FOODLOG_SCOPES]
    if invalid:
        raise AuthorizeError(
            "invalid_scope", f"Unsupported scopes: {' '.join(invalid)}"
        )
    registered_scopes = _client_registered_scopes(client)
    exceeded = [scope for scope in scopes if scope not in registered_scopes]
    if exceeded:
        raise AuthorizeError(
            "invalid_scope",
            f"Scopes exceed client registration: {' '.join(exceeded)}",
        )


def _validate_scopes_for_token(scopes: list[str]) -> None:
    invalid = [scope for scope in scopes if scope not in FOODLOG_SCOPES]
    if invalid:
        raise TokenError("invalid_scope", f"Unsupported scopes: {' '.join(invalid)}")


def _validate_resource_for_authorize(resource: str | None) -> str:
    expected = settings.public_mcp_resource_url
    requested = resource or expected
    if requested != expected:
        raise AuthorizeError("invalid_request", "Invalid resource")
    return requested


class FoodLogOAuthClientInformationFull(OAuthClientInformationFull):
    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            return super().validate_redirect_uri(redirect_uri)
        if self.redirect_uris is None:
            raise InvalidRedirectUriError(
                f"Redirect URI '{redirect_uri}' not registered for client"
            )
        if redirect_uri in self.redirect_uris:
            return redirect_uri
        if any(
            _loopback_callbacks_match(str(registered_uri), str(redirect_uri))
            for registered_uri in self.redirect_uris
        ):
            return redirect_uri
        raise InvalidRedirectUriError(
            f"Redirect URI '{redirect_uri}' not registered for client"
        )


class FoodLogOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self.session_factory() as session:
            row = session.get(OAuthClient, client_id)
            if row is None:
                return None
            return self._client_from_row(row)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        redirect_uris = [str(uri) for uri in client_info.redirect_uris or []]
        if not redirect_uris or any(
            not _redirect_uri_allowed(uri) for uri in redirect_uris
        ):
            raise RegistrationError("invalid_redirect_uri", "Unsupported redirect URI")

        token_endpoint_auth_method = client_info.token_endpoint_auth_method or "none"
        if token_endpoint_auth_method != "none":
            raise RegistrationError(
                "invalid_client_metadata", "Only public PKCE clients are supported"
            )

        if client_info.scope:
            invalid_scopes = [
                scope for scope in client_info.scope.split() if scope not in FOODLOG_SCOPES
            ]
            if invalid_scopes:
                raise RegistrationError(
                    "invalid_client_metadata",
                    f"Unsupported scopes: {' '.join(invalid_scopes)}",
                )

        grant_types = list(client_info.grant_types or [])
        if any(
            grant_type not in {"authorization_code", "refresh_token"}
            for grant_type in grant_types
        ):
            raise RegistrationError(
                "invalid_client_metadata", "Unsupported grant type"
            )

        response_types = list(client_info.response_types or [])
        if response_types != ["code"]:
            raise RegistrationError(
                "invalid_client_metadata", "Only code response type is supported"
            )

        client_id = client_info.client_id or _new_secret("client")
        issued_at = client_info.client_id_issued_at or now_epoch()

        with self.session_factory() as session:
            session.merge(
                OAuthClient(
                    client_id=client_id,
                    client_secret=None,
                    redirect_uris_json=_json_list(redirect_uris),
                    grant_types_json=_json_list(grant_types),
                    response_types_json=_json_list(response_types),
                    scope=client_info.scope or " ".join(FOODLOG_SCOPES),
                    client_name=client_info.client_name,
                    client_uri=str(client_info.client_uri)
                    if client_info.client_uri
                    else None,
                    logo_uri=str(client_info.logo_uri) if client_info.logo_uri else None,
                    contacts_json=_json_list(client_info.contacts),
                    tos_uri=str(client_info.tos_uri) if client_info.tos_uri else None,
                    policy_uri=str(client_info.policy_uri)
                    if client_info.policy_uri
                    else None,
                    jwks_uri=str(client_info.jwks_uri) if client_info.jwks_uri else None,
                    jwks_json=json.dumps(client_info.jwks)
                    if client_info.jwks is not None
                    else None,
                    software_id=client_info.software_id,
                    software_version=client_info.software_version,
                    token_endpoint_auth_method=token_endpoint_auth_method,
                    client_id_issued_at=issued_at,
                    client_secret_expires_at=None,
                )
            )
            session.commit()

        client_info.client_id = client_id
        client_info.client_id_issued_at = issued_at

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        redirect_uri = str(params.redirect_uri)
        if not _redirect_uri_allowed(redirect_uri):
            raise AuthorizeError("invalid_request", "Unsupported redirect URI")

        scopes = _requested_scopes(params.scopes, client)
        _validate_scopes_for_authorize(scopes, client)
        resource = _validate_resource_for_authorize(params.resource)
        request_id = _new_secret("authreq")

        with self.session_factory() as session:
            session.add(
                OAuthPendingAuthorization(
                    request_id=request_id,
                    client_id=client.client_id or "",
                    redirect_uri=redirect_uri,
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    scopes_json=_json_list(scopes),
                    state=params.state,
                    code_challenge=params.code_challenge,
                    resource=resource,
                    expires_at=utcnow() + datetime.timedelta(minutes=10),
                )
            )
            session.commit()

        return _append_query(
            f"{settings.public_base_url}/oauth/consent", {"request_id": request_id}
        )

    def get_pending_authorization(
        self, request_id: str
    ) -> OAuthPendingAuthorization | None:
        with self.session_factory() as session:
            row = session.get(OAuthPendingAuthorization, request_id)
            if row is None or row.expires_at <= utcnow():
                return None
            session.expunge(row)
            return row

    def approve_pending_authorization(self, request_id: str) -> str:
        with self.session_factory() as session:
            pending = session.get(OAuthPendingAuthorization, request_id)
            if pending is None or pending.expires_at <= utcnow():
                raise ValueError("Authorization request expired")

            code = _new_secret("code")
            redirect_uri = pending.redirect_uri
            state = pending.state
            session.add(
                OAuthAuthorizationCode(
                    code_hash=hash_token(code),
                    client_id=pending.client_id,
                    redirect_uri=redirect_uri,
                    redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
                    scopes_json=pending.scopes_json,
                    code_challenge=pending.code_challenge,
                    resource=pending.resource,
                    expires_at=utcnow()
                    + datetime.timedelta(
                        seconds=settings.oauth_authorization_code_ttl_seconds
                    ),
                )
            )
            session.delete(pending)
            session.commit()

        return _append_query(redirect_uri, {"code": code, "state": state})

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with self.session_factory() as session:
            row = session.get(OAuthAuthorizationCode, hash_token(authorization_code))
            if (
                row is None
                or row.consumed_at is not None
                or row.client_id != client.client_id
                or row.expires_at <= utcnow()
            ):
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=_load_json_list(row.scopes_json),
                expires_at=row.expires_at.replace(tzinfo=datetime.UTC).timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=AnyUrl(row.redirect_uri),
                redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                resource=row.resource,
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if authorization_code.client_id != client.client_id:
            raise TokenError("invalid_grant", "authorization code does not exist")
        _validate_scopes_for_token(authorization_code.scopes)

        with self.session_factory() as session:
            row = session.get(OAuthAuthorizationCode, hash_token(authorization_code.code))
            if (
                row is None
                or row.consumed_at is not None
                or row.client_id != client.client_id
                or row.expires_at <= utcnow()
            ):
                raise TokenError(
                    "invalid_grant", "authorization code is no longer valid"
                )

            row.consumed_at = utcnow()
            access_token, refresh_token = self._create_tokens(
                session=session,
                client_id=authorization_code.client_id,
                scopes=authorization_code.scopes,
                resource=authorization_code.resource,
            )
            session.commit()

        return OAuthToken(
            access_token=access_token,
            expires_in=settings.oauth_access_token_ttl_seconds,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        with self.session_factory() as session:
            row = session.get(OAuthRefreshToken, hash_token(refresh_token))
            if (
                row is None
                or row.revoked_at is not None
                or row.client_id != client.client_id
                or row.expires_at <= now_epoch()
            ):
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=_load_json_list(row.scopes_json),
                expires_at=row.expires_at,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if refresh_token.client_id != client.client_id:
            raise TokenError("invalid_grant", "refresh token does not exist")

        requested_scopes = scopes or refresh_token.scopes
        _validate_scopes_for_token(requested_scopes)
        extra_scopes = [
            scope for scope in requested_scopes if scope not in refresh_token.scopes
        ]
        if extra_scopes:
            raise TokenError(
                "invalid_scope",
                f"Cannot request scopes not granted by refresh token: {' '.join(extra_scopes)}",
            )

        with self.session_factory() as session:
            row = session.get(OAuthRefreshToken, hash_token(refresh_token.token))
            if (
                row is None
                or row.revoked_at is not None
                or row.client_id != client.client_id
                or row.expires_at <= now_epoch()
            ):
                raise TokenError("invalid_grant", "refresh token is no longer valid")

            row.revoked_at = utcnow()
            access_token, new_refresh_token = self._create_tokens(
                session=session,
                client_id=client.client_id or "",
                scopes=requested_scopes,
                resource=settings.public_mcp_resource_url,
            )
            row.replaced_by_hash = hash_token(new_refresh_token)
            session.commit()

        return OAuthToken(
            access_token=access_token,
            expires_in=settings.oauth_access_token_ttl_seconds,
            scope=" ".join(requested_scopes),
            refresh_token=new_refresh_token,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await FoodLogTokenVerifier(self.session_factory).verify_token(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_hash = hash_token(token.token)
        with self.session_factory() as session:
            access = session.get(OAuthAccessToken, token_hash)
            refresh = session.get(OAuthRefreshToken, token_hash)
            revoked_at = utcnow()

            if access is not None:
                access.revoked_at = revoked_at
                if access.refresh_token_hash:
                    paired_refresh = session.get(
                        OAuthRefreshToken, access.refresh_token_hash
                    )
                    if paired_refresh is not None:
                        paired_refresh.revoked_at = revoked_at

            if refresh is not None:
                refresh.revoked_at = revoked_at
                for paired_access in (
                    session.query(OAuthAccessToken)
                    .filter(OAuthAccessToken.refresh_token_hash == token_hash)
                    .all()
                ):
                    paired_access.revoked_at = revoked_at

            session.commit()

    def _create_tokens(
        self,
        session: Session,
        client_id: str,
        scopes: list[str],
        resource: str | None,
    ) -> tuple[str, str]:
        access_token = _new_secret("access")
        refresh_token = _new_secret("refresh")
        access_hash = hash_token(access_token)
        refresh_hash = hash_token(refresh_token)

        session.add(
            OAuthAccessToken(
                token_hash=access_hash,
                client_id=client_id,
                scopes_json=_json_list(scopes),
                resource=resource,
                expires_at=now_epoch() + settings.oauth_access_token_ttl_seconds,
                refresh_token_hash=refresh_hash,
            )
        )
        session.add(
            OAuthRefreshToken(
                token_hash=refresh_hash,
                client_id=client_id,
                scopes_json=_json_list(scopes),
                expires_at=now_epoch() + settings.oauth_refresh_token_ttl_seconds,
            )
        )
        return access_token, refresh_token

    def _client_from_row(self, row: OAuthClient) -> OAuthClientInformationFull:
        return FoodLogOAuthClientInformationFull(
            client_id=row.client_id,
            client_secret=row.client_secret,
            redirect_uris=[
                AnyUrl(uri) for uri in _load_json_list(row.redirect_uris_json)
            ],
            token_endpoint_auth_method=row.token_endpoint_auth_method,
            grant_types=_load_json_list(row.grant_types_json),
            response_types=_load_json_list(row.response_types_json),
            scope=row.scope,
            client_name=row.client_name,
            client_uri=AnyHttpUrl(row.client_uri) if row.client_uri else None,
            logo_uri=AnyHttpUrl(row.logo_uri) if row.logo_uri else None,
            contacts=_load_json_list(row.contacts_json) or None,
            tos_uri=AnyHttpUrl(row.tos_uri) if row.tos_uri else None,
            policy_uri=AnyHttpUrl(row.policy_uri) if row.policy_uri else None,
            jwks_uri=AnyHttpUrl(row.jwks_uri) if row.jwks_uri else None,
            jwks=json.loads(row.jwks_json) if row.jwks_json else None,
            software_id=row.software_id,
            software_version=row.software_version,
            client_id_issued_at=row.client_id_issued_at,
            client_secret_expires_at=row.client_secret_expires_at,
        )


class FoodLogTokenVerifier(TokenVerifier):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        with self.session_factory() as session:
            row = session.get(OAuthAccessToken, hash_token(token))
            if row is None or row.revoked_at is not None:
                return None
            if row.expires_at <= now_epoch():
                return None
            if row.resource != settings.public_mcp_resource_url:
                return None
            return AccessToken(
                token=token,
                client_id=row.client_id,
                scopes=_load_json_list(row.scopes_json),
                expires_at=row.expires_at,
                resource=row.resource,
            )


def login_secret_matches(candidate: str) -> bool:
    secret = settings.foodlog_oauth_login_secret
    if not secret:
        return False
    return hmac.compare_digest(candidate, secret)
