from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.auth import RefreshToken, Role, User


class UserRepository(ABC):
    @abstractmethod
    def get_by_id(self, user_id: UUID) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_username(self, username: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def ensure_user(self, username: str, password_hash: str, role: Role, tenant_id: UUID | None = None) -> User:
        raise NotImplementedError

    @abstractmethod
    def create_user(
        self,
        username: str,
        password_hash: str,
        role: Role,
        is_active: bool = True,
        tenant_id: UUID | None = None,
    ) -> User:
        raise NotImplementedError

    @abstractmethod
    def list_users(
        self,
        limit: int,
        offset: int,
        role: Role | None,
        is_active: bool | None,
        username: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[User], int]:
        raise NotImplementedError

    @abstractmethod
    def update_user(
        self,
        user_id: UUID,
        role: Role | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
        tenant_id: UUID | None = None,
    ) -> User:
        raise NotImplementedError

    @abstractmethod
    def count_active_admins(self) -> int:
        raise NotImplementedError


class RefreshTokenRepository(ABC):
    @abstractmethod
    def create(self, user_id: UUID, token_hash: str, expires_at) -> RefreshToken:
        raise NotImplementedError

    @abstractmethod
    def get_active_by_hash(self, token_hash: str) -> RefreshToken | None:
        raise NotImplementedError

    @abstractmethod
    def revoke_by_hash(self, token_hash: str) -> RefreshToken | None:
        raise NotImplementedError

    @abstractmethod
    def revoke_all_for_user(self, user_id: UUID) -> int:
        raise NotImplementedError
