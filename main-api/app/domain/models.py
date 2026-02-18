from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from .errors import ValidationError

InstanceStatus = Literal[
    "creating_pending",
    "updating_pending",
    "starting_pending",
    "stopping_pending",
    "deleting_pending",
    "running",
    "stopped",
    "error",
    "deleted",
]
TaskCommand = Literal["create", "update", "delete", "start", "stop"]
TaskStatus = Literal["queued", "running", "cancel_pending", "succeeded", "failed", "canceled"]


@dataclass(frozen=True)
class ResourceSpec:
    cpu: int
    memory_mib: int
    disk_gib: int

    def validate(self) -> None:
        if self.cpu <= 0:
            raise ValidationError("cpu must be > 0")
        if self.memory_mib <= 0:
            raise ValidationError("memory_mib must be > 0")
        if self.disk_gib <= 0:
            raise ValidationError("disk_gib must be > 0")


@dataclass
class Instance:
    id: UUID
    name: str | None
    resource_spec: ResourceSpec
    status: InstanceStatus
    ip_address: str | None
    host_node: str
    reserve_resources: bool
    last_task_id: UUID | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass
class InstanceTask:
    id: UUID
    instance_id: UUID
    command: TaskCommand
    status: TaskStatus
    request_id: UUID
    request_payload: dict[str, Any]
    result_payload: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


@dataclass
class AuditLog:
    id: UUID
    actor_user_id: UUID | None
    actor_username: str | None
    action: str
    target_type: str
    target_id: str | None
    request_id: UUID | None
    ip_address: str | None
    user_agent: str | None
    metadata: dict[str, Any]
    created_at: datetime
    tenant_id: UUID | None = None


@dataclass
class Tenant:
    id: UUID
    key: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class TenantQuota:
    tenant_id: UUID
    max_instances: int
    max_cpu: int
    max_memory_mib: int
    max_disk_gib: int
    updated_at: datetime


@dataclass
class TenantUsage:
    tenant_id: UUID
    used_instances: int
    used_cpu: int
    used_memory_mib: int
    used_disk_gib: int
