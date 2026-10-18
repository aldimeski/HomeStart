from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import User, utcnow
from ..schemas import LoginRequest, MeOut
from ..security import (
    SESSION_COOKIE,
    client_ip,
    create_session,
    current_session_token,
    delete_session,
    get_current_user,
    get_settings,
    hash_password,
    lockout_remaining,
    needs_rehash,
    purge_expired_sessions,
    record_login_attempt,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def me_payload(user: User) -> MeOut:
    return MeOut.model_validate({"user": user, "settings": user.settings})


@router.post("/login", response_model=MeOut)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    ip = client_ip(request)
    username = body.username.strip()

    remaining = lockout_remaining(db, settings, username, ip)
    if remaining:
        minutes = (remaining + 59) // 60
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
            headers={"Retry-After": str(remaining)},
        )

    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if not verify_password(user, body.password) or not user.is_active:
        record_login_attempt(db, username, ip, success=False)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    record_login_attempt(db, username, ip, success=True)
    if needs_rehash(user):
        user.password_hash = hash_password(body.password)
    user.last_login = utcnow()
    purge_expired_sessions(db, settings)
    token = create_session(db, user)
    db.commit()

    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    return me_payload(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    delete_session(db, current_session_token(request))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return me_payload(user)
