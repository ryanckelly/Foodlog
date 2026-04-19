import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class FoodEntry(Base):
    __tablename__ = "food_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meal_type: Mapped[str] = mapped_column(String(20))
    food_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(50))
    weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    carbs_g: Mapped[float] = mapped_column(Float)
    fat_g: Mapped[float] = mapped_column(Float)
    fiber_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sugar_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sodium_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_input: Mapped[str] = mapped_column(Text)
    logged_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_uris_json: Mapped[str] = mapped_column(Text)
    grant_types_json: Mapped[str] = mapped_column(Text)
    response_types_json: Mapped[str] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    contacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tos_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    jwks_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    jwks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    software_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_endpoint_auth_method: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    client_id_issued_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_secret_expires_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OAuthPendingAuthorization(Base):
    __tablename__ = "oauth_pending_authorizations"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean)
    scopes_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_challenge: Mapped[str] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class OAuthAuthorizationCode(Base):
    __tablename__ = "oauth_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean)
    scopes_json: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class OAuthAccessToken(Base):
    __tablename__ = "oauth_access_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    scopes_json: Mapped[str] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[int] = mapped_column(Integer)
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class OAuthRefreshToken(Base):
    __tablename__ = "oauth_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    scopes_json: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[int] = mapped_column(Integer)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
