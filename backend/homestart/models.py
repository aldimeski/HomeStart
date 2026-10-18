from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_USER)

THEMES = ("system", "light", "dark")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_USER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)

    settings: Mapped["UserSettings"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="joined"
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme: Mapped[str] = mapped_column(String(8), nullable=False, default="system")
    sidebar_collapsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sholink_expanded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="settings")


class AuthSession(Base):
    __tablename__ = "sessions"

    # Only a SHA-256 digest of the cookie token is stored, so a database copy cannot hijack sessions.
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str] = mapped_column(String(128), nullable=False, default="mdi:link-variant")
    open_in_new_tab: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class TasmotaDevice(Base):
    """A Tasmota device. Live state (power, sensors, WiFi) is kept in memory, not here."""

    __tablename__ = "tasmota_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Name set by an administrator; when empty the MQTT topic is shown.
    name: Mapped[str | None] = mapped_column(String(64))
    mqtt_topic: Mapped[str | None] = mapped_column(String(128), unique=True)
    host: Mapped[str | None] = mapped_column(String(253))
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    mac: Mapped[str | None] = mapped_column(String(17), index=True)
    hostname: Mapped[str | None] = mapped_column(String(64))
    friendly_names: Mapped[str | None] = mapped_column(Text)  # JSON list, one name per relay
    # Relay names set in HomeStart (JSON list by position); they override the device's FriendlyName.
    relay_names: Mapped[str | None] = mapped_column(Text)
    firmware: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    group_name: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="mqtt")  # mqtt | scan | manual
    auth_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Removed devices stay as a marker so retained MQTT messages do not bring them back.
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_enc: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
