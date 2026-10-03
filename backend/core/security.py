"""Password hashing and JWT issuing/verification.

passlib is intentionally avoided: passlib 1.7.4 crashes against bcrypt >= 5.0
(it reads the removed ``bcrypt.__about__.__version__`` attribute) and mis-handles
bcrypt's 72-byte password limit. The bcrypt library is used directly here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)
_settings = get_settings()

ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# bcrypt silently truncates anything beyond 72 bytes; reject longer input
# explicitly rather than storing a hash of a truncated password.
MAX_PASSWORD_BYTES = 72


class PasswordTooLongError(ValueError):
    """Raised when a plaintext password exceeds bcrypt's limit."""


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    encoded = plain_password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"Password must be at most {MAX_PASSWORD_BYTES} bytes; got {len(encoded)}"
        )
    salt = bcrypt.gensalt(rounds=_settings.bcrypt_rounds)
    return bcrypt.hashpw(encoded, salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    if not password_hash:
        return False
    try:
        encoded = plain_password.encode("utf-8")
        if len(encoded) > MAX_PASSWORD_BYTES:
            return False
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.warning("Password verification failed: %s", exc)
        return False


def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": uuid.uuid4().hex,
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, _settings.secret_key, algorithm=ALGORITHM)


def create_access_token(
    user_id: int, role: str, username: str, dept_id: int | None = None
) -> str:
    return _create_token(
        subject=str(user_id),
        token_type=TOKEN_TYPE_ACCESS,
        expires_delta=timedelta(minutes=_settings.access_token_expire_minutes),
        claims={"role": role, "username": username, "dept_id": dept_id},
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        subject=str(user_id),
        token_type=TOKEN_TYPE_REFRESH,
        expires_delta=timedelta(days=_settings.refresh_token_expire_days),
    )


class TokenError(Exception):
    """Raised when a token is invalid, expired, or of the wrong type."""


def decode_token(token: str, expected_type: str = TOKEN_TYPE_ACCESS) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _settings.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token")
    return payload
