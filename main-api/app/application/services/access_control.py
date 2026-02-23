from __future__ import annotations

from uuid import UUID

from app.domain.auth import User
from app.domain.errors import (
    ForbiddenError,
    InstanceNotFoundError,
    TaskNotFoundError,
    TenantInactiveError,
    TenantNotFoundError,
    ValidationError,
)
from app.ports import TaskRepository, TenantRepository


def resolve_tenant_scope_for_list(
    current_user: User, requested_tenant_id: UUID | None
) -> UUID | None:
    if current_user.role == "admin":
        return requested_tenant_id
    if current_user.tenant_id is None:
        raise ForbiddenError("tenant scope required")
    if (
        requested_tenant_id is not None
        and requested_tenant_id != current_user.tenant_id
    ):
        raise TenantNotFoundError("tenant not found")
    return current_user.tenant_id


def resolve_tenant_for_create(
    current_user: User, requested_tenant_id: UUID | None
) -> UUID:
    if current_user.role == "admin":
        if requested_tenant_id is None:
            raise ValidationError("tenant_id is required for admin")
        return requested_tenant_id
    if current_user.tenant_id is None:
        raise ForbiddenError("tenant scope required")
    if (
        requested_tenant_id is not None
        and requested_tenant_id != current_user.tenant_id
    ):
        raise TenantNotFoundError("tenant not found")
    return current_user.tenant_id


def ensure_instance_access(current_user: User, instance_tenant_id: UUID) -> None:
    if current_user.role != "admin" and current_user.tenant_id != instance_tenant_id:
        raise InstanceNotFoundError("instance not found")


def ensure_task_access(current_user: User, task_tenant_id: UUID) -> None:
    if current_user.role != "admin" and current_user.tenant_id != task_tenant_id:
        raise TaskNotFoundError("task not found")


async def ensure_mutation_allowed_for_user_tenant(
    tenant_repository: TenantRepository, current_user: User
) -> None:
    if current_user.role == "admin":
        return
    if current_user.tenant_id is None:
        raise ForbiddenError("tenant scope required")
    tenant_is_active = await tenant_repository.is_active(current_user.tenant_id)
    if tenant_is_active is None or not tenant_is_active:
        raise TenantInactiveError("tenant is inactive")


async def get_task_tenant_id_or_raise(
    task_repository: TaskRepository, task_id: UUID
) -> UUID:
    tenant_id = await task_repository.get_tenant_id(task_id)
    if tenant_id is None:
        raise TaskNotFoundError("task not found")
    return tenant_id
