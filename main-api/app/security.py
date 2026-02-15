from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt


class InvalidTokenError(Exception):
    pass


def hash_password(password: str, *, iterations: int = 390000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = encoded_hash.split("$", maxsplit=3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text.encode("ascii"))
        expected_digest = base64.b64decode(digest_text.encode("ascii"))
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected_digest)


def create_access_token(
    *,
    user_id: UUID,
    username: str,
    role: str,
    secret: str,
    algorithm: str,
    expire_minutes: int,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=expire_minutes)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, expires_at


def create_refresh_token(
    *,
    user_id: UUID,
    username: str,
    role: str,
    secret: str,
    algorithm: str,
    expire_days: int,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=expire_days)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "refresh",
        "jti": str(uuid4()),
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, expires_at


def decode_access_token(*, token: str, secret: str, algorithms: list[str]) -> dict:
    try:
        payload = jwt.decode(token, secret, algorithms=algorithms)
    except jwt.PyJWTError as exc:  # pragma: no cover
        raise InvalidTokenError("invalid access token") from exc
    if payload.get("type") != "access":
        raise InvalidTokenError("invalid token type")
    return payload


def decode_refresh_token(*, token: str, secret: str, algorithms: list[str]) -> dict:
    try:
        payload = jwt.decode(token, secret, algorithms=algorithms)
    except jwt.PyJWTError as exc:  # pragma: no cover
        raise InvalidTokenError("invalid refresh token") from exc
    if payload.get("type") != "refresh":
        raise InvalidTokenError("invalid token type")
    if not payload.get("jti"):
        raise InvalidTokenError("invalid refresh token")
    return payload


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
