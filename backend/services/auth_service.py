"""Authentication service: registration, login, token refresh, profile.

All password handling goes through backend.core.security. This module owns the
transactional user-account rules and raises domain errors that the API layer
translates into HTTP responses.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.core.security import (
    PasswordTooLongError,
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.models.complaint import AuditLog
from backend.models.people import AppUser, Staff
from backend.models.reference import Department
from backend.schemas.auth import RegisterRequest

logger = get_logger(__name__)
_settings = get_settings()

# Students self-register; staff and admin accounts are provisioned by an admin.
SELF_REGISTERABLE_ROLE = "STUDENT"


class AuthError(Exception):
    """Authentication or account error carrying a user-facing message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _department_name(db: Session, dept_id: int | None) -> str | None:
    if dept_id is None:
        return None
    dept = db.get(Department, dept_id)
    return dept.dept_name if dept else None


def _to_response(user: AppUser, db: Session):
    from backend.schemas.auth import UserResponse

    staff_profile = db.execute(
        select(Staff).where(Staff.user_id == user.user_id)
    ).scalar_one_or_none()

    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        dept_id=user.dept_id,
        dept_name=_department_name(db, user.dept_id),
        staff_id=staff_profile.staff_id if staff_profile else None,
        usn=user.usn,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def register_student(db: Session, payload: RegisterRequest) -> AppUser:
    """Create a STUDENT account.

    Rejects the request if the username, email or USN is already taken. The
    UNIQUE constraints are the real guard; this pre-check exists only to
    return a friendly error instead of a 500 from an IntegrityError.
    """
    username = payload.username.strip().lower()
    email = payload.email.lower()

    existing = db.execute(
        select(AppUser).where(
            (AppUser.username == username) | (AppUser.email == email)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AuthError("Username or email is already registered", status_code=409)

    if payload.usn:
        usn_taken = db.execute(
            select(AppUser).where(AppUser.usn == payload.usn)
        ).scalar_one_or_none()
        if usn_taken is not None:
            raise AuthError("That USN is already registered", status_code=409)

    try:
        password_hash = hash_password(payload.password)
    except PasswordTooLongError as exc:
        raise AuthError(str(exc), status_code=400) from exc

    user = AppUser(
        username=username,
        email=email,
        password_hash=password_hash,
        full_name=payload.full_name.strip(),
        role=SELF_REGISTERABLE_ROLE,  # never client-controlled
        dept_id=None,
        usn=payload.usn,
        phone=payload.phone,
        semester=payload.semester,
        section_name=payload.section_name,
        hostel_name=payload.hostel_name,
    )
    db.add(user)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AuthError("Username, email or USN is already registered", 409) from exc

    db.add(
        AuditLog(
            actor_id=user.user_id,
            action="USER_REGISTERED",
            entity_type="app_user",
            entity_id=str(user.user_id),
            details=f"Self-registered student {user.username}",
        )
    )
    db.commit()
    db.refresh(user)
    logger.info("Registered student %s (id=%s)", user.username, user.user_id)
    return user


def authenticate(db: Session, username: str, password: str) -> AppUser:
    """Verify credentials and return the user, updating last_login_at."""
    normalized = username.strip().lower()

    user = db.execute(
        select(AppUser).where(AppUser.username == normalized)
    ).scalar_one_or_none()

    if user is None:
        # Also allow login by email for convenience.
        user = db.execute(
            select(AppUser).where(AppUser.email == normalized)
        ).scalar_one_or_none()

    if user is None:
        # Constant-ish failure: still perform a hash comparison so that a
        # missing username and a wrong password take comparable time.
        verify_password(password, hash_password("timing-equalizer"))
        raise AuthError("Incorrect username or password", status_code=401)

    if not verify_password(password, user.password_hash):
        raise AuthError("Incorrect username or password", status_code=401)

    if not user.is_active:
        raise AuthError("Account is disabled. Contact the administrator.", 403)

    user.last_login_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            actor_id=user.user_id,
            action="LOGIN_SUCCESS",
            entity_type="app_user",
            entity_id=str(user.user_id),
        )
    )
    db.commit()
    db.refresh(user)
    return user


def issue_tokens(user: AppUser, db: Session):
    """Build the access/refresh token pair for a user."""
    staff_profile = db.execute(
        select(Staff).where(Staff.user_id == user.user_id)
    ).scalar_one_or_none()

    access = create_access_token(
        user_id=user.user_id,
        role=user.role,
        username=user.username,
        dept_id=user.dept_id,
    )
    refresh = create_refresh_token(user.user_id)

    from backend.schemas.auth import TokenResponse

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        expires_in=_settings.access_token_expire_minutes * 60,
        user=_to_response(user, db),
    )


def refresh_access_token(db: Session, refresh_token: str):
    """Exchange a valid refresh token for a new access token."""
    try:
        payload = decode_token(refresh_token, expected_type=TOKEN_TYPE_REFRESH)
    except Exception as exc:
        raise AuthError("Invalid or expired refresh token", 401) from exc

    user = db.get(AppUser, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("User account is no longer active", 401)

    access = create_access_token(
        user_id=user.user_id,
        role=user.role,
        username=user.username,
        dept_id=user.dept_id,
    )
    from backend.schemas.auth import TokenResponse

    return TokenResponse(
        access_token=access,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=_settings.access_token_expire_minutes * 60,
        user=_to_response(user, db),
    )


def change_password(db: Session, user: AppUser, current_password: str, new_password: str) -> None:
    """Change a user's own password after verifying the current one."""
    if not verify_password(current_password, user.password_hash):
        raise AuthError("Current password is incorrect", status_code=403)

    try:
        password_hash = hash_password(new_password)
    except PasswordTooLongError as exc:
        raise AuthError(str(exc), 400) from exc

    user.password_hash = password_hash
    db.add(
        AuditLog(
            actor_id=user.user_id,
            action="PASSWORD_CHANGED",
            entity_type="app_user",
            entity_id=str(user.user_id),
        )
    )
    db.commit()


def count_users_by_role(db: Session) -> dict[str, int]:
    """User counts per role (admin dashboard)."""
    rows = db.execute(
        select(AppUser.role, func.count()).group_by(AppUser.role)
    ).all()
    return {role: count for role, count in rows}
