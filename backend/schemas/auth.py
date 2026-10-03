"""Pydantic request/response schemas for the auth API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Student self-registration.

    Role is deliberately NOT client-settable: students may only register as
    STUDENT. Staff and admin accounts are created by an administrator, which is
    what stops a student from self-registering as staff and reaching the
    assignment endpoints.
    """

    username: str = Field(min_length=3, max_length=60, pattern=r"^[a-zA-Z0-9._-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=2, max_length=120)
    usn: str | None = Field(default=None, max_length=30)
    phone: str | None = Field(default=None, max_length=20)
    semester: int | None = Field(default=None, ge=1, le=10)
    section_name: str | None = Field(default=None, max_length=20)
    hostel_name: str | None = Field(default=None, max_length=40)

    @field_validator("username")
    @classmethod
    def lowercase_username(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    user: "UserResponse"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    email: str
    full_name: str
    role: str
    dept_id: int | None = None
    dept_name: str | None = None
    staff_id: int | None = None
    usn: str | None = None
    is_active: bool = True
    created_at: datetime | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)


TokenResponse.model_rebuild()
