"""FastAPI dependencies: database session, current user, permission gates."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.permissions import (
    Action,
    Scope,
    UserContext,
    require_action,
    scope_for,
)
from backend.core.security import TokenError, decode_token
from backend.models.people import AppUser, Staff

# auto_error=False so we can return a clean 401 instead of FastAPI's default
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AppUser:
    """Resolve the authenticated user from the Bearer token (API endpoints)."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token"
        )

    user = db.get(AppUser, int(user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    return user


def get_current_user_from_cookie(
    access_token_cookie: str | None = Cookie(None, alias="access_token"),
    db: Session = Depends(get_db),
) -> AppUser:
    """Resolve the authenticated user from HttpOnly cookie (HTML page routes)."""
    if not access_token_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = decode_token(access_token_cookie, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token"
        )

    user = db.get(AppUser, int(user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    return user


def get_user_context(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)) -> UserContext:
    """Wrap the current user with the fields scope checks need."""
    staff_profile = (
        db.query(Staff).filter(Staff.user_id == user.user_id).one_or_none()
    )
    return UserContext(
        user_id=user.user_id,
        role=user.role,
        dept_id=user.dept_id,
        staff_id=staff_profile.staff_id if staff_profile else None,
        username=user.username,
    )


def require_permission(action: Action):
    """Dependency factory enforcing that the caller may perform ``action``.

    Usage::

        @router.post("/complaints", dependencies=[Depends(require_permission(Action.CREATE_COMPLAINT))])
    """

    def _dependency(
        user: AppUser = Depends(get_current_user),
        context: UserContext = Depends(get_user_context),
    ) -> UserContext:
        require_action(user.role, action)
        return context

    return _dependency


def require_scope(required: Scope):
    """Dependency factory requiring a minimum scope on the view action."""

    def _dependency(
        user: AppUser = Depends(get_current_user),
        context: UserContext = Depends(get_user_context),
    ) -> UserContext:
        from backend.core.permissions import has_scope

        if not has_scope(user.role, Action.VIEW_ALL_COMPLAINTS, required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this view",
            )
        return context

    return _dependency
