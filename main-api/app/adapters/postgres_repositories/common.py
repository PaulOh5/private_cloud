from __future__ import annotations

from app.domain.auth import RefreshToken, User
from app.domain.models import (
    AuditLog,
    Instance,
    InstanceTask,
    OutboxMessage,
    ResourceSpec,
    Tenant,
    TenantQuota,
    TenantUsage,
)


def to_instance(model) -> Instance:
    return Instance(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        resource_spec=ResourceSpec(
            cpu=model.cpu, memory_mib=model.memory_mib, disk_gib=model.disk_gib
        ),
        status=model.status.value if hasattr(model.status, "value") else model.status,
        ip_address=str(model.ip_address) if model.ip_address else None,
        host_node=model.host_node,
        reserve_resources=bool(model.reserve_resources),
        last_task_id=model.last_task_id,
        deleted_at=model.deleted_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_task(model) -> InstanceTask:
    return InstanceTask(
        id=model.id,
        instance_id=model.instance_id,
        command=model.command.value
        if hasattr(model.command, "value")
        else model.command,
        status=model.status.value if hasattr(model.status, "value") else model.status,
        request_id=model.request_id,
        request_payload=model.request_payload or {},
        result_payload=model.result_payload,
        error_code=model.error_code,
        error_message=model.error_message,
        attempt_count=model.attempt_count,
        max_attempts=model.max_attempts,
        created_at=model.created_at,
        started_at=model.started_at,
        finished_at=model.finished_at,
        updated_at=model.updated_at,
    )


def to_outbox(model) -> OutboxMessage:
    return OutboxMessage(
        id=model.id,
        topic=model.topic,
        task_id=model.task_id,
        request_id=model.request_id,
        payload=model.payload or {},
        status=model.status.value if hasattr(model.status, "value") else model.status,
        attempt_count=model.attempt_count,
        max_attempts=model.max_attempts,
        next_attempt_at=model.next_attempt_at,
        locked_by=model.locked_by,
        lock_expires_at=model.lock_expires_at,
        last_error=model.last_error,
        sent_at=model.sent_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_user(model) -> User:
    return User(
        id=model.id,
        username=model.username,
        password_hash=model.password_hash,
        role=model.role.value if hasattr(model.role, "value") else model.role,
        tenant_id=model.tenant_id,
        is_active=bool(model.is_active),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_refresh_token(model) -> RefreshToken:
    return RefreshToken(
        id=model.id,
        user_id=model.user_id,
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_audit_log(model) -> AuditLog:
    return AuditLog(
        id=model.id,
        tenant_id=model.tenant_id,
        actor_user_id=model.actor_user_id,
        actor_username=model.actor_username,
        action=model.action,
        target_type=model.target_type,
        target_id=model.target_id,
        request_id=model.request_id,
        ip_address=str(model.ip_address) if model.ip_address else None,
        user_agent=model.user_agent,
        metadata=model.metadata_ or {},
        created_at=model.created_at,
    )


def to_tenant(model) -> Tenant:
    return Tenant(
        id=model.id,
        key=model.key,
        name=model.name,
        is_active=bool(model.is_active),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_tenant_quota(model) -> TenantQuota:
    return TenantQuota(
        tenant_id=model.tenant_id,
        max_instances=int(model.max_instances),
        max_cpu=int(model.max_cpu),
        max_memory_mib=int(model.max_memory_mib),
        max_disk_gib=int(model.max_disk_gib),
        updated_at=model.updated_at,
    )


def to_tenant_usage(row) -> TenantUsage:
    return TenantUsage(
        tenant_id=row.tenant_id,
        used_instances=int(row.used_instances),
        used_cpu=int(row.used_cpu),
        used_memory_mib=int(row.used_memory_mib),
        used_disk_gib=int(row.used_disk_gib),
    )
