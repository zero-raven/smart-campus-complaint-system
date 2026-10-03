"""Password hashing and JWT unit tests."""

from __future__ import annotations

import pytest

from backend.core.security import (
    MAX_PASSWORD_BYTES,
    PasswordTooLongError,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("Campus@2026")
        assert hashed != "Campus@2026"
        assert hashed.startswith("$2")

    def test_verify_accepts_correct_password(self):
        hashed = hash_password("Campus@2026")
        assert verify_password("Campus@2026", hashed) is True

    def test_verify_rejects_wrong_password(self):
        hashed = hash_password("Campus@2026")
        assert verify_password("wrong-password", hashed) is False

    def test_same_password_produces_different_hashes(self):
        """bcrypt salts each hash, so two hashes must differ."""
        assert hash_password("Campus@2026") != hash_password("Campus@2026")

    def test_oversized_password_is_rejected(self):
        """bcrypt truncates at 72 bytes; refuse rather than hash a prefix."""
        with pytest.raises(PasswordTooLongError):
            hash_password("x" * (MAX_PASSWORD_BYTES + 1))

    def test_oversized_password_never_verifies(self):
        assert verify_password("x" * (MAX_PASSWORD_BYTES + 5), hash_password("Campus@2026")) is False

    def test_empty_hash_never_verifies(self):
        assert verify_password("anything", "") is False

    def test_malformed_hash_returns_false_not_exception(self):
        assert verify_password("anything", "not-a-bcrypt-hash") is False


class TestTokens:
    def test_access_token_roundtrip(self):
        token = create_access_token(user_id=7, role="STUDENT", username="nikhil")
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == "7"
        assert payload["role"] == "STUDENT"
        assert payload["username"] == "nikhil"

    def test_refresh_token_rejected_as_access_token(self):
        """Type confusion must fail: a refresh token must not grant access."""
        token = create_refresh_token(user_id=7)
        with pytest.raises(TokenError):
            decode_token(token, expected_type="access")

    def test_access_token_rejected_as_refresh_token(self):
        token = create_access_token(user_id=7, role="ADMIN", username="admin")
        with pytest.raises(TokenError):
            decode_token(token, expected_type="refresh")

    def test_garbage_token_rejected(self):
        with pytest.raises(TokenError):
            decode_token("not.a.jwt", expected_type="access")

    def test_token_signed_with_wrong_key_rejected(self):
        import jwt

        forged = jwt.encode(
            {"sub": "1", "type": "access", "role": "ADMIN"}, "wrong-key", algorithm="HS256"
        )
        with pytest.raises(TokenError):
            decode_token(forged, expected_type="access")

    def test_alg_none_token_rejected(self):
        """The 'alg: none' downgrade attack must not be accepted."""
        import jwt

        forged = jwt.encode({"sub": "1", "type": "access"}, key="", algorithm="none")
        with pytest.raises(TokenError):
            decode_token(forged, expected_type="access")
