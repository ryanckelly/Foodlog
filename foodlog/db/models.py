import datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
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


class GoogleOAuthToken(Base):
    """Singleton row holding the encrypted Google Health refresh token."""
    __tablename__ = "google_oauth_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("id = 1", name="google_oauth_token_singleton"),)


class DailyActivity(Base):
    __tablename__ = "daily_activity"

    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int] = mapped_column(Integer, nullable=False)
    active_calories_kcal: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class BodyComposition(Base):
    __tablename__ = "body_composition"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    measured_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class RestingHeartRate(Base):
    __tablename__ = "resting_heart_rate"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    measured_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    bpm: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class SleepSession(Base):
    __tablename__ = "sleep_sessions"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    start_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class Workout(Base):
    __tablename__ = "workouts"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    start_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    calories_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    hr_samples = relationship(
        "WorkoutHrSample",
        back_populates="workout",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WorkoutHrSample(Base):
    __tablename__ = "workout_hr_samples"

    workout_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("workouts.external_id", ondelete="CASCADE"),
        primary_key=True,
    )
    sample_at: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    bpm: Mapped[int] = mapped_column(Integer, nullable=False)

    workout = relationship("Workout", back_populates="hr_samples")
