from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.auth import RefreshToken, Role, User
from app.domain.errors import ConflictError, NotFoundError
from app.ports import RefreshTokenRepository, UserRepository

from .common import _to_refresh_token, _to_user


class PostgresUserRepository(UserRepository):
    def __init__(self, session: Session):
        self.session = session

    def create_user(
        self,
        username: str,
        password_hash: str,
        role: Role,
        is_active: bool = True,
        tenant_id: UUID | None = None,
    ) -> User:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                INSERT INTO users (id, username, password_hash, role, tenant_id, is_active, created_at, updated_at)
                VALUES (:id, :username, :password_hash, :role, :tenant_id, :is_active, :created_at, :updated_at)
                ON CONFLICT (username) DO NOTHING
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "username": username,
                "password_hash": password_hash,
                "role": role,
                "tenant_id": str(tenant_id) if tenant_id else None,
                "is_active": is_active,
                "created_at": now,
                "updated_at": now,
            },
        ).mappings().first()
        if not row:
            raise ConflictError(f"username {username} already exists")
        return _to_user(row)

    def get_by_id(self, user_id: UUID) -> User | None:
        row = self.session.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {"id": str(user_id)},
        ).mappings().first()
        return _to_user(row) if row else None

    def get_by_username(self, username: str) -> User | None:
        row = self.session.execute(
            text("SELECT * FROM users WHERE username = :username"),
            {"username": username},
        ).mappings().first()
        return _to_user(row) if row else None

    def ensure_user(self, username: str, password_hash: str, role: Role, tenant_id: UUID | None = None) -> User:
        try:
            return self.create_user(
                username=username,
                password_hash=password_hash,
                role=role,
                is_active=True,
                tenant_id=tenant_id,
            )
        except ConflictError:
            pass
        existing = self.get_by_username(username)
        if not existing:
            raise NotFoundError(f"user {username} not found")
        return existing

    def list_users(
        self,
        limit: int,
        offset: int,
        role: Role | None,
        is_active: bool | None,
        username: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[User], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if role:
            conditions.append("role = :role")
            params["role"] = role
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active
        if username:
            conditions.append("username ILIKE :username")
            params["username"] = f"%{username}%"
        if tenant_id is not None:
            conditions.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self.session.execute(
            text(
                f"""
                SELECT * FROM users
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM users {where_clause}"),
            params,
        ).mappings().one()
        return ([_to_user(row) for row in rows], int(count_row["total"]))

    def update_user(
        self,
        user_id: UUID,
        role: Role | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
        tenant_id: UUID | None = None,
    ) -> User:
        row = self.session.execute(
            text(
                """
                UPDATE users
                SET role = COALESCE(:role, role),
                    tenant_id = CASE
                        WHEN COALESCE(:role, role) = 'admin' THEN NULL
                        WHEN CAST(:tenant_id AS UUID) IS NOT NULL THEN CAST(:tenant_id AS UUID)
                        ELSE tenant_id
                    END,
                    is_active = COALESCE(:is_active, is_active),
                    password_hash = COALESCE(:password_hash, password_hash),
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(user_id),
                "role": role,
                "tenant_id": str(tenant_id) if tenant_id else None,
                "is_active": is_active,
                "password_hash": password_hash,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"user {user_id} not found")
        return _to_user(row)

    def count_active_admins(self) -> int:
        row = self.session.execute(
            text("SELECT COUNT(*) AS total FROM users WHERE role = 'admin' AND is_active = true"),
        ).mappings().one()
        return int(row["total"])


class PostgresRefreshTokenRepository(RefreshTokenRepository):
    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: UUID, token_hash: str, expires_at) -> RefreshToken:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, revoked_at, created_at, updated_at)
                VALUES (:id, :user_id, :token_hash, :expires_at, NULL, :created_at, :updated_at)
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "user_id": str(user_id),
                "token_hash": token_hash,
                "expires_at": expires_at,
                "created_at": now,
                "updated_at": now,
            },
        ).mappings().one()
        return _to_refresh_token(row)

    def get_active_by_hash(self, token_hash: str) -> RefreshToken | None:
        row = self.session.execute(
            text(
                """
                SELECT *
                FROM refresh_tokens
                WHERE token_hash = :token_hash
                  AND revoked_at IS NULL
                  AND expires_at > :now
                """
            ),
            {"token_hash": token_hash, "now": datetime.now(timezone.utc)},
        ).mappings().first()
        return _to_refresh_token(row) if row else None

    def revoke_by_hash(self, token_hash: str) -> RefreshToken | None:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                UPDATE refresh_tokens
                SET revoked_at = COALESCE(revoked_at, :revoked_at),
                    updated_at = :updated_at
                WHERE token_hash = :token_hash
                RETURNING *
                """
            ),
            {
                "token_hash": token_hash,
                "revoked_at": now,
                "updated_at": now,
            },
        ).mappings().first()
        return _to_refresh_token(row) if row else None

    def revoke_all_for_user(self, user_id: UUID) -> int:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                WITH updated AS (
                    UPDATE refresh_tokens
                    SET revoked_at = COALESCE(revoked_at, :revoked_at),
                        updated_at = :updated_at
                    WHERE user_id = :user_id
                      AND revoked_at IS NULL
                    RETURNING 1
                )
                SELECT COUNT(*) AS total FROM updated
                """
            ),
            {
                "user_id": str(user_id),
                "revoked_at": now,
                "updated_at": now,
            },
        ).mappings().one()
        return int(row["total"])


