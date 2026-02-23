from datetime import datetime, timezone
from uuid import uuid4

import jwt
import pytest

from app.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password_roundtrip():
    encoded = hash_password("s3cret-password")
    assert verify_password("s3cret-password", encoded) is True
    assert verify_password("wrong-password", encoded) is False


def test_access_token_roundtrip():
    user_id = uuid4()
    token, expires_at = create_access_token(
        user_id=user_id,
        username="alice",
        role="admin",
        secret="test-secret",
        algorithm="HS256",
        expire_minutes=15,
        now=datetime.now(timezone.utc),
    )
    assert expires_at.tzinfo is not None

    payload = decode_access_token(
        token=token, secret="test-secret", algorithms=["HS256"]
    )
    assert payload["sub"] == str(user_id)
    assert payload["username"] == "alice"
    assert payload["role"] == "admin"


def test_decode_access_token_rejects_wrong_type():
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "type": "refresh",
            "exp": datetime(2099, 1, 1, tzinfo=timezone.utc),
        },
        "test-secret",
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token=token, secret="test-secret", algorithms=["HS256"])


def test_refresh_token_roundtrip_and_hash():
    user_id = uuid4()
    refresh_token, expires_at = create_refresh_token(
        user_id=user_id,
        username="alice",
        role="admin",
        secret="test-secret",
        algorithm="HS256",
        expire_days=14,
        now=datetime.now(timezone.utc),
    )
    assert expires_at.tzinfo is not None

    payload = decode_refresh_token(
        token=refresh_token, secret="test-secret", algorithms=["HS256"]
    )
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "refresh"
    assert payload.get("jti")
    assert hash_token(refresh_token) == hash_token(refresh_token)
