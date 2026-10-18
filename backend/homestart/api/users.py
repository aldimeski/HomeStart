from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ROLE_ADMIN, User, UserSettings
from ..schemas import PasswordChange, PasswordReset, SettingsOut, SettingsUpdate, UserCreate, UserOut, UserUpdate
from ..security import (
    current_session_token,
    delete_user_sessions,
    get_current_user,
    hash_password,
    require_admin,
    validate_new_password,
    verify_password,
)

router = APIRouter(prefix="/api/users", tags=["users"])


def _username_taken(db: Session, username: str, exclude_id: int | None = None) -> bool:
    stmt = select(User.id).where(func.lower(User.username) == username.lower())
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) is not None


def _active_admin_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == ROLE_ADMIN, User.is_active.is_(True)))


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


# /me routes are declared before /{user_id} so "me" is never parsed as an id.
@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    body: PasswordChange,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(user, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    validate_new_password(body.new_password)
    user.password_hash = hash_password(body.new_password)
    delete_user_sessions(db, user.id, keep_token=current_session_token(request))
    db.commit()


@router.put("/me/settings", response_model=SettingsOut)
def update_own_settings(
    body: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = user.settings
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(settings, field, value)
    db.commit()
    return settings


@router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(func.lower(User.username))).all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if _username_taken(db, body.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    validate_new_password(body.password)
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=body.is_active,
        settings=UserSettings(),
    )
    db.add(user)
    db.commit()
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)

    if body.username is not None and body.username != user.username:
        if _username_taken(db, body.username, exclude_id=user.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
        user.username = body.username

    loses_admin = (body.role is not None and body.role != ROLE_ADMIN) or body.is_active is False
    if loses_admin and user.role == ROLE_ADMIN and user.is_active:
        if user.id == admin.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot remove your own administrator access")
        if _active_admin_count(db) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one active administrator is required")

    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            delete_user_sessions(db, user.id)
    db.commit()
    return user


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: int,
    body: PasswordReset,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)
    validate_new_password(body.new_password)
    user.password_hash = hash_password(body.new_password)
    keep = current_session_token(request) if user.id == admin.id else None
    delete_user_sessions(db, user.id, keep_token=keep)
    db.commit()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    if user.role == ROLE_ADMIN and user.is_active and _active_admin_count(db) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one active administrator is required")
    db.delete(user)
    db.commit()
