"""Password hashing, sessions and login rate limiting."""

import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import Settings
from .db import get_db
from .models import ROLE_ADMIN, AuthSession, LoginAttempt, User, utcnow

SESSION_COOKIE = "homestart_session"
CSRF_HEADER = "X-HomeStart"
MIN_PASSWORD_LENGTH = 4
# Global per-IP ceiling, so one client cannot spray guesses across many usernames.
MAX_FAILED_PER_IP_FACTOR = 4
# last_seen is written at most this often to avoid a database write on every request.
SESSION_TOUCH_INTERVAL = timedelta(seconds=60)

_hasher = PasswordHasher()  # argon2-cffi defaults to Argon2id
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(user: User | None, password: str) -> bool:
    if user is None:
        # Spend the same time as a real check, so response timing does not reveal valid usernames.
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except VerificationError:
            pass
        return False
    try:
        return _hasher.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(user: User) -> bool:
    return _hasher.check_needs_rehash(user.password_hash)


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long",
        )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user.id))
    return token


def delete_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))


def delete_user_sessions(db: Session, user_id: int, keep_token: str | None = None) -> None:
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep_token:
        stmt = stmt.where(AuthSession.token_hash != _token_hash(keep_token))
    db.execute(stmt)


def purge_expired_sessions(db: Session, settings: Settings) -> None:
    cutoff = utcnow() - timedelta(minutes=settings.session_timeout_minutes)
    db.execute(delete(AuthSession).where(AuthSession.last_seen < cutoff))


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def lockout_remaining(db: Session, settings: Settings, username: str, ip: str) -> int:
    """Seconds until login is allowed again for this username/IP, or 0 when not locked."""
    since = utcnow() - timedelta(minutes=settings.lockout_minutes)

    last_success = db.scalar(
        select(func.max(LoginAttempt.created_at)).where(
            LoginAttempt.username == username, LoginAttempt.ip == ip, LoginAttempt.success.is_(True)
        )
    )
    window_start = max(since, last_success) if last_success else since

    pair_failures = select(LoginAttempt.created_at).where(
        LoginAttempt.username == username,
        LoginAttempt.ip == ip,
        LoginAttempt.success.is_(False),
        LoginAttempt.created_at > window_start,
    )
    ip_failures = select(LoginAttempt.created_at).where(
        LoginAttempt.ip == ip, LoginAttempt.success.is_(False), LoginAttempt.created_at > since
    )

    for query, limit in (
        (pair_failures, settings.max_failed_logins),
        (ip_failures, settings.max_failed_logins * MAX_FAILED_PER_IP_FACTOR),
    ):
        times = db.scalars(query.order_by(LoginAttempt.created_at.desc()).limit(limit)).all()
        if len(times) >= limit:
            unlock_at = times[-1] + timedelta(minutes=settings.lockout_minutes)
            remaining = int((unlock_at - utcnow()).total_seconds())
            if remaining > 0:
                return remaining
    return 0


def record_login_attempt(db: Session, username: str, ip: str, success: bool) -> None:
    db.add(LoginAttempt(username=username, ip=ip, success=success))


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def current_session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = current_session_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    auth_session = db.get(AuthSession, _token_hash(token))
    now = utcnow()
    if auth_session is None or now - auth_session.last_seen > timedelta(minutes=settings.session_timeout_minutes):
        if auth_session is not None:
            db.delete(auth_session)
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    user = db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    if now - auth_session.last_seen > SESSION_TOUCH_INTERVAL:
        auth_session.last_seen = now
        db.commit()
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return user
