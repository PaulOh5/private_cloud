from __future__ import annotations
from dataclasses import dataclass
from typing import cast
from uuid import UUID
from app.domain.auth import Role, User
from app.ports import UserRepository


@dataclass(frozen=True)
class ListUsersQuery:
    limit: int
    offset: int
    role: str | None = None
    is_active: bool | None = None
    username: str | None = None
    tenant_id: UUID | None = None


@dataclass(frozen=True)
class ListUsersResult:
    items: list[User]
    total: int


class ListUsersHandler:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def handle(self, query: ListUsersQuery) -> ListUsersResult:
        items, total = await self.user_repository.list_users(
            limit=query.limit,
            offset=query.offset,
            role=cast(Role | None, query.role),
            is_active=query.is_active,
            username=query.username,
            tenant_id=query.tenant_id,
        )
        return ListUsersResult(items=items, total=total)
