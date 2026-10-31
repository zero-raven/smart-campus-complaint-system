"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.config import get_settings
from backend.core.deps import get_current_user
from backend.core.permissions import Action
from backend.models.people import AppUser
from backend.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from backend.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
_settings = get_settings()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserResponse:
    """Student self-registration. Role is fixed to STUDENT."""
    try:
        user = auth_service.register_student(db, payload)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return auth_service._to_response(user, db)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    """Exchange credentials for an access/refresh token pair."""
    try:
        user = auth_service.authenticate(db, payload.username, payload.password)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    token_data = auth_service.issue_tokens(user, db)
    
    # Set access token as HttpOnly cookie for HTML page routes
    response.set_cookie(
        key="access_token",
        value=token_data.access_token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=_settings.access_token_expire_minutes * 60,
        path="/",
    )
    return token_data


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        return auth_service.refresh_access_token(db, payload.refresh_token)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/me", response_model=UserResponse)
def me(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)) -> UserResponse:
    """Current authenticated profile, including resolved role and department."""
    return auth_service._to_response(user, db)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        auth_service.change_password(
            db, user, payload.current_password, payload.new_password
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@router.get("/logout", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def logout(response: Response) -> None:
    """Clear the access token cookie."""
    response.delete_cookie(key="access_token", path="/", httponly=True, samesite="lax")
