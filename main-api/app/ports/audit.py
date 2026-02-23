from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.models import AuditLog


class AuditLogRepository(ABC):
    @abstractmethod
    async def create(
        self,
        *,
        tenant_id: UUID | None,
        actor_user_id: UUID | None,
        actor_username: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        request_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        metadata: dict,
    ) -> AuditLog:
        raise NotImplementedError

    @abstractmethod
    async def get(self, log_id: UUID) -> AuditLog | None:
        raise NotImplementedError

    @abstractmethod
    async def list(
        self,
        *,
        limit: int,
        offset: int,
        actor_user_id: UUID | None,
        action: str | None,
        target_type: str | None,
        request_id: UUID | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[AuditLog], int]:
        raise NotImplementedError
