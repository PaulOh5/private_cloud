from __future__ import annotations
from uuid import UUID
from app.domain.auth import User
from app.domain.errors import UserNotFoundError
from app.ports import UserRepository


class GetUserHandler:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def handle(self, user_id: UUID) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"user {user_id} not found")
        return user
