from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol
from uuid import UUID

from app.domain.models import OutboxMessage


class VmProvisioningPort(ABC):
    @abstractmethod
    async def publish_command(
        self, command: str, payload: dict, task_id: UUID, request_id: UUID
    ) -> None:
        raise NotImplementedError


class VmImageSyncError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class VmImageSyncPort(Protocol):
    async def sync_images(self) -> dict: ...


class CommandOutboxRepository(ABC):
    @abstractmethod
    async def enqueue_command(
        self,
        *,
        topic: str,
        payload: dict,
        task_id: UUID,
        request_id: UUID,
        max_attempts: int,
    ) -> OutboxMessage:
        raise NotImplementedError

    @abstractmethod
    async def claim_batch(
        self,
        *,
        locker_id: str,
        limit: int,
        lock_timeout_seconds: int,
    ) -> list[OutboxMessage]:
        raise NotImplementedError

    @abstractmethod
    async def mark_sent(self, message_id: UUID) -> OutboxMessage:
        raise NotImplementedError

    @abstractmethod
    async def mark_retry(
        self, message_id: UUID, *, delay_seconds: int, error_message: str | None
    ) -> OutboxMessage:
        raise NotImplementedError

    @abstractmethod
    async def mark_failed(
        self, message_id: UUID, *, error_message: str | None
    ) -> OutboxMessage:
        raise NotImplementedError

    @abstractmethod
    async def recover_stuck_publishing(self) -> int:
        raise NotImplementedError
