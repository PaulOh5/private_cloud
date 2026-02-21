from __future__ import annotations

from app.domain.auth import RefreshToken, User
from app.domain.models import AuditLog, Instance, InstanceTask, OutboxMessage, ResourceSpec, Tenant, TenantQuota, TenantUsage


def _to_instance(row) -> Instance:
    return Instance(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        resource_spec=ResourceSpec(cpu=row["cpu"], memory_mib=row["memory_mib"], disk_gib=row["disk_gib"]),
        status=row["status"],
        ip_address=str(row["ip_address"]) if row["ip_address"] else None,
        host_node=row["host_node"],
        reserve_resources=bool(row["reserve_resources"]),
        last_task_id=row["last_task_id"],
        deleted_at=row["deleted_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_task(row) -> InstanceTask:
    return InstanceTask(
        id=row["id"],
        instance_id=row["instance_id"],
        command=row["command"],
        status=row["status"],
        request_id=row["request_id"],
        request_payload=row["request_payload"] or {},
        result_payload=row["result_payload"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        updated_at=row["updated_at"],
    )


def _to_outbox(row) -> OutboxMessage:
    return OutboxMessage(
        id=row["id"],
        topic=row["topic"],
        task_id=row["task_id"],
        request_id=row["request_id"],
        payload=row["payload"] or {},
        status=row["status"],
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        next_attempt_at=row["next_attempt_at"],
        locked_by=row["locked_by"],
        lock_expires_at=row["lock_expires_at"],
        last_error=row["last_error"],
        sent_at=row["sent_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_user(row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        role=row["role"],
        tenant_id=row["tenant_id"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_refresh_token(row) -> RefreshToken:
    return RefreshToken(
        id=row["id"],
        user_id=row["user_id"],
        token_hash=row["token_hash"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_audit_log(row) -> AuditLog:
    return AuditLog(
        id=row["id"],
        tenant_id=row["tenant_id"],
        actor_user_id=row["actor_user_id"],
        actor_username=row["actor_username"],
        action=row["action"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        request_id=row["request_id"],
        ip_address=str(row["ip_address"]) if row["ip_address"] else None,
        user_agent=row["user_agent"],
        metadata=row["metadata"] or {},
        created_at=row["created_at"],
    )


def _to_tenant(row) -> Tenant:
    return Tenant(
        id=row["id"],
        key=row["key"],
        name=row["name"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_tenant_quota(row) -> TenantQuota:
    return TenantQuota(
        tenant_id=row["tenant_id"],
        max_instances=int(row["max_instances"]),
        max_cpu=int(row["max_cpu"]),
        max_memory_mib=int(row["max_memory_mib"]),
        max_disk_gib=int(row["max_disk_gib"]),
        updated_at=row["updated_at"],
    )


def _to_tenant_usage(row) -> TenantUsage:
    return TenantUsage(
        tenant_id=row["tenant_id"],
        used_instances=int(row["used_instances"]),
        used_cpu=int(row["used_cpu"]),
        used_memory_mib=int(row["used_memory_mib"]),
        used_disk_gib=int(row["used_disk_gib"]),
    )
