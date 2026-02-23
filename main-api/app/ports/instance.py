from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.domain.models import (
    Instance,
    InstanceTask,
    ResourceSpec,
    TaskCommand,
    TaskStatus,
)


class InstanceRepository(ABC):
    @abstractmethod
    async def get_for_update(self, instance_id: UUID) -> Instance | None:
        raise NotImplementedError

    @abstractmethod
    async def create(self, instance: Instance) -> Instance:
        raise NotImplementedError

    @abstractmethod
    async def update_spec(
        self,
        instance_id: UUID,
        spec: ResourceSpec,
        status: str,
        ip_address: str | None,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
    ) -> Instance:
        raise NotImplementedError

    @abstractmethod
    async def update_state(
        self,
        instance_id: UUID,
        status: str,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
        ip_address: str | None,
    ) -> Instance:
        raise NotImplementedError


class InstanceReadRepository(ABC):
    @abstractmethod
    async def get(
        self, instance_id: UUID, tenant_id: UUID | None = None
    ) -> Instance | None:
        raise NotImplementedError

    @abstractmethod
    async def list(
        self,
        limit: int,
        offset: int,
        status: str | None,
        name: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[Instance], int]:
        raise NotImplementedError


class TaskRepository(ABC):
    @abstractmethod
    async def has_active_task(self, instance_id: UUID) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def create_task(self, task: InstanceTask) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    async def get(self, task_id: UUID) -> InstanceTask | None:
        raise NotImplementedError

    @abstractmethod
    async def get_tenant_id(self, task_id: UUID) -> UUID | None:
        raise NotImplementedError

    @abstractmethod
    async def get_for_update(self, task_id: UUID) -> InstanceTask | None:
        raise NotImplementedError

    @abstractmethod
    async def list(
        self,
        limit: int,
        offset: int,
        status: TaskStatus | None,
        instance_id: UUID | None,
        command: TaskCommand | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[InstanceTask], int]:
        raise NotImplementedError

    @abstractmethod
    async def mark_running(self, task_id: UUID, attempt_count: int) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    async def mark_cancel_pending(
        self,
        task_id: UUID,
        canceled_by: UUID | None,
        cancel_reason: str | None,
    ) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    async def mark_canceled(
        self,
        task_id: UUID,
        attempt_count: int,
        canceled_by: UUID | None,
        cancel_reason: str | None,
        result_payload: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    async def clone_for_retry(
        self,
        source_task: InstanceTask,
        new_task_id: UUID,
        new_request_id: UUID,
        created_at: datetime,
    ) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    async def mark_terminal(
        self,
        task_id: UUID,
        status: TaskStatus,
        attempt_count: int,
        result_payload: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> InstanceTask:
        raise NotImplementedError
