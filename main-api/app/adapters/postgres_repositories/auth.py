from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth import RefreshToken, Role, User
from app.domain.errors import ConflictError, NotFoundError
from app.ports import RefreshTokenRepository, UserRepository

from .common import to_refresh_token, to_user
from .orm.auth import RefreshTokenModel, UserModel


class PostgresUserRepository(UserRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self,
        username: str,
        password_hash: str,
        role: Role,
        is_active: bool = True,
        tenant_id: UUID | None = None,
    ) -> User:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(UserModel)
            .values(
                id=uuid4(),
                username=username,
                password_hash=password_hash,
                role=role,
                tenant_id=tenant_id,
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[UserModel.username])
            .returning(UserModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise ConflictError(f"username {username} already exists")
        return to_user(model)

    async def get_by_id(self, user_id: UUID) -> User | None:
        model = await self.session.scalar(
            select(UserModel).where(UserModel.id == user_id)
        )
        return to_user(model) if model else None

    async def get_by_username(self, username: str) -> User | None:
        model = await self.session.scalar(
            select(UserModel).where(UserModel.username == username)
        )
        return to_user(model) if model else None

    async def ensure_user(
        self,
        username: str,
        password_hash: str,
        role: Role,
        tenant_id: UUID | None = None,
    ) -> User:
        try:
            return await self.create_user(
                username=username,
                password_hash=password_hash,
                role=role,
                is_active=True,
                tenant_id=tenant_id,
            )
        except ConflictError:
            pass
        existing = await self.get_by_username(username)
        if not existing:
            raise NotFoundError(f"user {username} not found")
        return existing

    async def list_users(
        self,
        limit: int,
        offset: int,
        role: Role | None,
        is_active: bool | None,
        username: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[User], int]:
        conditions = []
        if role:
            conditions.append(UserModel.role == role)
        if is_active is not None:
            conditions.append(UserModel.is_active == is_active)
        if username:
            conditions.append(UserModel.username.ilike(f"%{username}%"))
        if tenant_id is not None:
            conditions.append(UserModel.tenant_id == tenant_id)

        where_clause = and_(*conditions) if conditions else None

        stmt = (
            select(UserModel)
            .order_by(UserModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count()).select_from(UserModel)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
            count_stmt = count_stmt.where(where_clause)

        models = (await self.session.scalars(stmt)).all()
        total = int((await self.session.scalar(count_stmt)) or 0)
        return ([to_user(model) for model in models], total)

    async def update_user(
        self,
        user_id: UUID,
        role: Role | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
        tenant_id: UUID | None = None,
    ) -> User:
        next_role = func.coalesce(role, UserModel.role)
        tenant_case = case(
            (next_role == "admin", None),
            (literal(tenant_id is not None), tenant_id),
            else_=UserModel.tenant_id,
        )
        stmt = (
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(
                role=next_role,
                tenant_id=tenant_case,
                is_active=func.coalesce(is_active, UserModel.is_active),
                password_hash=func.coalesce(password_hash, UserModel.password_hash),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(UserModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"user {user_id} not found")
        return to_user(model)

    async def count_active_admins(self) -> int:
        stmt = (
            select(func.count())
            .select_from(UserModel)
            .where(and_(UserModel.role == "admin", UserModel.is_active.is_(True)))
        )
        return int((await self.session.scalar(stmt)) or 0)


class PostgresRefreshTokenRepository(RefreshTokenRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: UUID, token_hash: str, expires_at) -> RefreshToken:
        now = datetime.now(timezone.utc)
        model = RefreshTokenModel(
            id=uuid4(),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        await self.session.flush()
        return to_refresh_token(model)

    async def get_active_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshTokenModel).where(
            and_(
                RefreshTokenModel.token_hash == token_hash,
                RefreshTokenModel.revoked_at.is_(None),
                RefreshTokenModel.expires_at > datetime.now(timezone.utc),
            )
        )
        model = await self.session.scalar(stmt)
        return to_refresh_token(model) if model else None

    async def revoke_by_hash(self, token_hash: str) -> RefreshToken | None:
        now = datetime.now(timezone.utc)
        stmt = (
            update(RefreshTokenModel)
            .where(RefreshTokenModel.token_hash == token_hash)
            .values(
                revoked_at=func.coalesce(RefreshTokenModel.revoked_at, now),
                updated_at=now,
            )
            .returning(RefreshTokenModel)
        )
        model = await self.session.scalar(stmt)
        return to_refresh_token(model) if model else None

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            update(RefreshTokenModel)
            .where(
                and_(
                    RefreshTokenModel.user_id == user_id,
                    RefreshTokenModel.revoked_at.is_(None),
                )
            )
            .values(
                revoked_at=func.coalesce(RefreshTokenModel.revoked_at, now),
                updated_at=now,
            )
            .returning(RefreshTokenModel.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return len(rows)
