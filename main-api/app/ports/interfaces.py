from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.auth import RefreshToken, Role, User
from app.domain.models import AuditLog, Instance, InstanceTask, ResourceSpec, TaskCommand, TaskStatus


class InstanceRepository(ABC):
    @abstractmethod
    def get_for_update(self, instance_id: UUID) -> Instance | None:
        raise NotImplementedError

    @abstractmethod
    def create(self, instance: Instance) -> Instance:
        raise NotImplementedError

    @abstractmethod
    def update_spec(
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
    def update_state(
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
    def get(self, instance_id: UUID) -> Instance | None:
        raise NotImplementedError

    @abstractmethod
    def list(self, limit: int, offset: int, status: str | None, name: str | None) -> tuple[list[Instance], int]:
        raise NotImplementedError


class TaskRepository(ABC):
    @abstractmethod
    def has_active_task(self, instance_id: UUID) -> bool:
        raise NotImplementedError

    @abstractmethod
    def create_task(self, task: InstanceTask) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    def get(self, task_id: UUID) -> InstanceTask | None:
        raise NotImplementedError

    @abstractmethod
    def get_for_update(self, task_id: UUID) -> InstanceTask | None:
        raise NotImplementedError

    @abstractmethod
    def list(
        self,
        limit: int,
        offset: int,
        status: TaskStatus | None,
        instance_id: UUID | None,
        command: TaskCommand | None,
    ) -> tuple[list[InstanceTask], int]:
        raise NotImplementedError

    @abstractmethod
    def mark_running(self, task_id: UUID, attempt_count: int) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    def mark_cancel_pending(
        self,
        task_id: UUID,
        canceled_by: UUID | None,
        cancel_reason: str | None,
    ) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    def mark_canceled(
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
    def clone_for_retry(
        self,
        source_task: InstanceTask,
        new_task_id: UUID,
        new_request_id: UUID,
        created_at: datetime,
    ) -> InstanceTask:
        raise NotImplementedError

    @abstractmethod
    def mark_terminal(
        self,
        task_id: UUID,
        status: TaskStatus,
        attempt_count: int,
        result_payload: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> InstanceTask:
        raise NotImplementedError


class VmProvisioningPort(ABC):
    @abstractmethod
    def publish_command(self, command: str, payload: dict, task_id: UUID, request_id: UUID) -> None:
        raise NotImplementedError


class UserRepository(ABC):
    @abstractmethod
    def get_by_id(self, user_id: UUID) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_username(self, username: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def ensure_user(self, username: str, password_hash: str, role: Role) -> User:
        raise NotImplementedError

    @abstractmethod
    def create_user(self, username: str, password_hash: str, role: Role, is_active: bool = True) -> User:
        raise NotImplementedError

    @abstractmethod
    def list_users(
        self,
        limit: int,
        offset: int,
        role: Role | None,
        is_active: bool | None,
        username: str | None,
    ) -> tuple[list[User], int]:
        raise NotImplementedError

    @abstractmethod
    def update_user(
        self,
        user_id: UUID,
        role: Role | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
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


class AuditLogRepository(ABC):
    @abstractmethod
    def create(
        self,
        *,
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
    def get(self, log_id: UUID) -> AuditLog | None:
        raise NotImplementedError

    @abstractmethod
    def list(
        self,
        *,
        limit: int,
        offset: int,
        actor_user_id: UUID | None,
        action: str | None,
        target_type: str | None,
        request_id: UUID | None,
    ) -> tuple[list[AuditLog], int]:
        raise NotImplementedError


@dataclass(frozen=True)
class CapacityCheckInput:
    host_node: str
    current: ResourceSpec | None
    requested: ResourceSpec


class ResourceAccountingPort(Protocol):
    def assert_capacity(self, check: CapacityCheckInput) -> None:
        ...


class UnitOfWork(Protocol):
    def advisory_lock(self, key: int) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...
