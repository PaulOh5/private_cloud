from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.auth import RefreshToken, Role, User
from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import AuditLog, Instance, InstanceTask, OutboxMessage, ResourceSpec, Tenant, TenantQuota, TenantUsage
from app.ports.interfaces import (
    AuditLogRepository,
    CommandOutboxRepository,
    InstanceReadRepository,
    InstanceRepository,
    RefreshTokenRepository,
    TenantQuotaRepository,
    TenantRepository,
    TenantUsageReadPort,
    TaskRepository,
    UserRepository,
)


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


class PostgresInstanceRepository(InstanceRepository):
    def __init__(self, session: Session):
        self.session = session

    def get_for_update(self, instance_id: UUID) -> Instance | None:
        row = self.session.execute(
            text("SELECT * FROM instances WHERE id = :id FOR UPDATE"),
            {"id": str(instance_id)},
        ).mappings().first()
        return _to_instance(row) if row else None

    def create(self, instance: Instance) -> Instance:
        row = self.session.execute(
            text(
                """
                INSERT INTO instances (
                    id, tenant_id, name, cpu, memory_mib, disk_gib,
                    status, ip_address, host_node, reserve_resources,
                    last_task_id, deleted_at, created_at, updated_at
                )
                VALUES (
                    :id, :tenant_id, :name, :cpu, :memory_mib, :disk_gib,
                    :status, :ip_address, :host_node, :reserve_resources,
                    :last_task_id, :deleted_at, :created_at, :updated_at
                )
                RETURNING *
                """
            ),
            {
                "id": str(instance.id),
                "tenant_id": str(instance.tenant_id),
                "name": instance.name,
                "cpu": instance.resource_spec.cpu,
                "memory_mib": instance.resource_spec.memory_mib,
                "disk_gib": instance.resource_spec.disk_gib,
                "status": instance.status,
                "ip_address": instance.ip_address,
                "host_node": instance.host_node,
                "reserve_resources": instance.reserve_resources,
                "last_task_id": str(instance.last_task_id) if instance.last_task_id else None,
                "deleted_at": instance.deleted_at,
                "created_at": instance.created_at,
                "updated_at": instance.updated_at,
            },
        ).mappings().one()
        return _to_instance(row)

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
        row = self.session.execute(
            text(
                """
                UPDATE instances
                SET cpu = :cpu,
                    memory_mib = :memory_mib,
                    disk_gib = :disk_gib,
                    status = :status,
                    ip_address = :ip_address,
                    reserve_resources = :reserve_resources,
                    last_task_id = :last_task_id,
                    deleted_at = :deleted_at,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(instance_id),
                "cpu": spec.cpu,
                "memory_mib": spec.memory_mib,
                "disk_gib": spec.disk_gib,
                "status": status,
                "ip_address": ip_address,
                "reserve_resources": reserve_resources,
                "last_task_id": str(last_task_id) if last_task_id else None,
                "deleted_at": deleted_at,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"instance {instance_id} not found")
        return _to_instance(row)

    def update_state(
        self,
        instance_id: UUID,
        status: str,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
        ip_address: str | None,
    ) -> Instance:
        row = self.session.execute(
            text(
                """
                UPDATE instances
                SET status = :status,
                    reserve_resources = :reserve_resources,
                    last_task_id = :last_task_id,
                    deleted_at = :deleted_at,
                    ip_address = :ip_address,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(instance_id),
                "status": status,
                "reserve_resources": reserve_resources,
                "last_task_id": str(last_task_id) if last_task_id else None,
                "deleted_at": deleted_at,
                "ip_address": ip_address,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"instance {instance_id} not found")
        return _to_instance(row)


class PostgresInstanceReadRepository(InstanceReadRepository):
    def __init__(self, session: Session):
        self.session = session

    def get(self, instance_id: UUID, tenant_id: UUID | None = None) -> Instance | None:
        conditions: list[str] = ["id = :id"]
        params: dict[str, object] = {"id": str(instance_id)}
        if tenant_id is not None:
            conditions.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)
        row = self.session.execute(
            text(f"SELECT * FROM instances WHERE {' AND '.join(conditions)}"),
            params,
        ).mappings().first()
        return _to_instance(row) if row else None

    def list(
        self,
        limit: int,
        offset: int,
        status: str | None,
        name: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[Instance], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if name:
            conditions.append("name ILIKE :name")
            params["name"] = f"%{name}%"
        if tenant_id is not None:
            conditions.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self.session.execute(
            text(
                f"""
                SELECT * FROM instances
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()

        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM instances {where_clause}"),
            params,
        ).mappings().one()

        return ([_to_instance(row) for row in rows], int(count_row["total"]))


class PostgresTaskRepository(TaskRepository):
    def __init__(self, session: Session):
        self.session = session

    def has_active_task(self, instance_id: UUID) -> bool:
        row = self.session.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM instance_tasks
                    WHERE instance_id = :instance_id
                      AND status IN ('queued', 'running', 'cancel_pending')
                ) AS has_active
                """
            ),
            {"instance_id": str(instance_id)},
        ).mappings().one()
        return bool(row["has_active"])

    def create_task(self, task: InstanceTask) -> InstanceTask:
        row = self.session.execute(
            text(
                """
                INSERT INTO instance_tasks (
                    id, instance_id, command, status, request_id,
                    request_payload, result_payload,
                    error_code, error_message,
                    retry_of_task_id, canceled_by, cancel_reason,
                    attempt_count, max_attempts,
                    created_at, started_at, finished_at, updated_at
                )
                VALUES (
                    :id, :instance_id, :command, :status, :request_id,
                    CAST(:request_payload AS JSONB), CAST(:result_payload AS JSONB),
                    :error_code, :error_message,
                    :retry_of_task_id, :canceled_by, :cancel_reason,
                    :attempt_count, :max_attempts,
                    :created_at, :started_at, :finished_at, :updated_at
                )
                RETURNING *
                """
            ),
            {
                "id": str(task.id),
                "instance_id": str(task.instance_id),
                "command": task.command,
                "status": task.status,
                "request_id": str(task.request_id),
                "request_payload": json.dumps(task.request_payload),
                "result_payload": json.dumps(task.result_payload) if task.result_payload is not None else None,
                "error_code": task.error_code,
                "error_message": task.error_message,
                "retry_of_task_id": None,
                "canceled_by": None,
                "cancel_reason": None,
                "attempt_count": task.attempt_count,
                "max_attempts": task.max_attempts,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "finished_at": task.finished_at,
                "updated_at": task.updated_at,
            },
        ).mappings().one()
        return _to_task(row)

    def get(self, task_id: UUID) -> InstanceTask | None:
        row = self.session.execute(
            text("SELECT * FROM instance_tasks WHERE id = :id"),
            {"id": str(task_id)},
        ).mappings().first()
        return _to_task(row) if row else None

    def get_for_update(self, task_id: UUID) -> InstanceTask | None:
        row = self.session.execute(
            text("SELECT * FROM instance_tasks WHERE id = :id FOR UPDATE"),
            {"id": str(task_id)},
        ).mappings().first()
        return _to_task(row) if row else None

    def list(
        self,
        limit: int,
        offset: int,
        status: str | None,
        instance_id: UUID | None,
        command: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[InstanceTask], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if status:
            conditions.append("t.status = :status")
            params["status"] = status
        if instance_id:
            conditions.append("t.instance_id = :instance_id")
            params["instance_id"] = str(instance_id)
        if command:
            conditions.append("t.command = :command")
            params["command"] = command
        if tenant_id is not None:
            conditions.append("i.tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self.session.execute(
            text(
                f"""
                SELECT t.*
                FROM instance_tasks t
                JOIN instances i ON i.id = t.instance_id
                {where_clause}
                ORDER BY t.created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()

        count_row = self.session.execute(
            text(
                f"""
                SELECT COUNT(*) AS total
                FROM instance_tasks t
                JOIN instances i ON i.id = t.instance_id
                {where_clause}
                """
            ),
            params,
        ).mappings().one()

        return ([_to_task(row) for row in rows], int(count_row["total"]))

    def mark_running(self, task_id: UUID, attempt_count: int) -> InstanceTask:
        row = self.session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'running',
                    attempt_count = :attempt_count,
                    started_at = COALESCE(started_at, :started_at),
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(task_id),
                "attempt_count": attempt_count,
                "started_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"task {task_id} not found")
        return _to_task(row)

    def mark_cancel_pending(
        self,
        task_id: UUID,
        canceled_by: UUID | None,
        cancel_reason: str | None,
    ) -> InstanceTask:
        row = self.session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'cancel_pending',
                    canceled_by = COALESCE(:canceled_by, canceled_by),
                    cancel_reason = COALESCE(:cancel_reason, cancel_reason),
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(task_id),
                "canceled_by": str(canceled_by) if canceled_by else None,
                "cancel_reason": cancel_reason,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"task {task_id} not found")
        return _to_task(row)

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
        row = self.session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'canceled',
                    attempt_count = :attempt_count,
                    result_payload = CAST(:result_payload AS JSONB),
                    error_code = :error_code,
                    error_message = :error_message,
                    canceled_by = COALESCE(:canceled_by, canceled_by),
                    cancel_reason = COALESCE(:cancel_reason, cancel_reason),
                    finished_at = :finished_at,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(task_id),
                "attempt_count": attempt_count,
                "result_payload": json.dumps(result_payload) if result_payload is not None else None,
                "error_code": error_code,
                "error_message": error_message,
                "canceled_by": str(canceled_by) if canceled_by else None,
                "cancel_reason": cancel_reason,
                "finished_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"task {task_id} not found")
        return _to_task(row)

    def clone_for_retry(
        self,
        source_task: InstanceTask,
        new_task_id: UUID,
        new_request_id: UUID,
        created_at: datetime,
    ) -> InstanceTask:
        row = self.session.execute(
            text(
                """
                INSERT INTO instance_tasks (
                    id, instance_id, command, status, request_id,
                    request_payload, result_payload,
                    error_code, error_message,
                    retry_of_task_id, canceled_by, cancel_reason,
                    attempt_count, max_attempts,
                    created_at, started_at, finished_at, updated_at
                )
                VALUES (
                    :id, :instance_id, :command, 'queued', :request_id,
                    CAST(:request_payload AS JSONB), NULL,
                    NULL, NULL,
                    :retry_of_task_id, NULL, NULL,
                    0, :max_attempts,
                    :created_at, NULL, NULL, :updated_at
                )
                RETURNING *
                """
            ),
            {
                "id": str(new_task_id),
                "instance_id": str(source_task.instance_id),
                "command": source_task.command,
                "request_id": str(new_request_id),
                "request_payload": json.dumps(source_task.request_payload),
                "retry_of_task_id": str(source_task.id),
                "max_attempts": source_task.max_attempts,
                "created_at": created_at,
                "updated_at": created_at,
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"failed to clone task {source_task.id}")
        return _to_task(row)

    def mark_terminal(
        self,
        task_id: UUID,
        status: str,
        attempt_count: int,
        result_payload: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> InstanceTask:
        row = self.session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = :status,
                    attempt_count = :attempt_count,
                    result_payload = CAST(:result_payload AS JSONB),
                    error_code = :error_code,
                    error_message = :error_message,
                    finished_at = :finished_at,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(task_id),
                "status": status,
                "attempt_count": attempt_count,
                "result_payload": json.dumps(result_payload) if result_payload is not None else None,
                "error_code": error_code,
                "error_message": error_message,
                "finished_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"task {task_id} not found")
        return _to_task(row)


class PostgresCommandOutboxRepository(CommandOutboxRepository):
    def __init__(self, session: Session, notify_channel: str | None = None):
        self.session = session
        self.notify_channel = notify_channel

    def enqueue_command(
        self,
        *,
        topic: str,
        payload: dict,
        task_id: UUID,
        request_id: UUID,
        max_attempts: int,
    ) -> OutboxMessage:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                INSERT INTO command_outbox (
                    id, topic, task_id, request_id, payload, status,
                    attempt_count, max_attempts, next_attempt_at,
                    locked_by, lock_expires_at, last_error, sent_at,
                    created_at, updated_at
                )
                VALUES (
                    :id, :topic, :task_id, :request_id, CAST(:payload AS JSONB), 'queued',
                    0, :max_attempts, :next_attempt_at,
                    NULL, NULL, NULL, NULL,
                    :created_at, :updated_at
                )
                ON CONFLICT (task_id, topic, request_id)
                DO UPDATE SET updated_at = EXCLUDED.updated_at
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "topic": topic,
                "task_id": str(task_id),
                "request_id": str(request_id),
                "payload": json.dumps(payload),
                "max_attempts": max(1, int(max_attempts)),
                "next_attempt_at": now,
                "created_at": now,
                "updated_at": now,
            },
        ).mappings().one()
        outbox = _to_outbox(row)
        if self.notify_channel:
            self.session.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": self.notify_channel, "payload": str(outbox.id)},
            )
        return outbox

    def claim_batch(
        self,
        *,
        locker_id: str,
        limit: int,
        lock_timeout_seconds: int,
    ) -> list[OutboxMessage]:
        now = datetime.now(timezone.utc)
        lock_expires_at = now + timedelta(seconds=max(1, int(lock_timeout_seconds)))
        rows = self.session.execute(
            text(
                """
                WITH picked AS (
                    SELECT id
                    FROM command_outbox
                    WHERE status = 'queued'
                      AND next_attempt_at <= :now
                    ORDER BY created_at ASC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE command_outbox o
                SET status = 'publishing',
                    locked_by = :locker_id,
                    lock_expires_at = :lock_expires_at,
                    updated_at = :updated_at
                FROM picked
                WHERE o.id = picked.id
                RETURNING o.*
                """
            ),
            {
                "now": now,
                "limit": max(1, int(limit)),
                "locker_id": locker_id,
                "lock_expires_at": lock_expires_at,
                "updated_at": now,
            },
        ).mappings().all()
        return [_to_outbox(row) for row in rows]

    def mark_sent(self, message_id: UUID) -> OutboxMessage:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                UPDATE command_outbox
                SET status = 'sent',
                    sent_at = :sent_at,
                    locked_by = NULL,
                    lock_expires_at = NULL,
                    last_error = NULL,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {"id": str(message_id), "sent_at": now, "updated_at": now},
        ).mappings().first()
        if not row:
            raise NotFoundError(f"outbox message {message_id} not found")
        return _to_outbox(row)

    def mark_retry(self, message_id: UUID, *, delay_seconds: int, error_message: str | None) -> OutboxMessage:
        now = datetime.now(timezone.utc)
        next_attempt_at = now + timedelta(seconds=max(1, int(delay_seconds)))
        row = self.session.execute(
            text(
                """
                UPDATE command_outbox
                SET status = 'queued',
                    attempt_count = attempt_count + 1,
                    next_attempt_at = :next_attempt_at,
                    locked_by = NULL,
                    lock_expires_at = NULL,
                    last_error = :last_error,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(message_id),
                "next_attempt_at": next_attempt_at,
                "last_error": error_message,
                "updated_at": now,
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"outbox message {message_id} not found")
        return _to_outbox(row)

    def mark_failed(self, message_id: UUID, *, error_message: str | None) -> OutboxMessage:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                UPDATE command_outbox
                SET status = 'failed',
                    attempt_count = attempt_count + 1,
                    locked_by = NULL,
                    lock_expires_at = NULL,
                    last_error = :last_error,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(message_id),
                "last_error": error_message,
                "updated_at": now,
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"outbox message {message_id} not found")
        return _to_outbox(row)

    def recover_stuck_publishing(self) -> int:
        row = self.session.execute(
            text(
                """
                WITH recovered AS (
                    UPDATE command_outbox
                    SET status = 'queued',
                        locked_by = NULL,
                        lock_expires_at = NULL,
                        next_attempt_at = :now,
                        updated_at = :now
                    WHERE status = 'publishing'
                      AND lock_expires_at IS NOT NULL
                      AND lock_expires_at < :now
                    RETURNING 1
                )
                SELECT COUNT(*) AS total FROM recovered
                """
            ),
            {"now": datetime.now(timezone.utc)},
        ).mappings().one()
        return int(row["total"])


class PostgresUserRepository(UserRepository):
    def __init__(self, session: Session):
        self.session = session

    def create_user(
        self,
        username: str,
        password_hash: str,
        role: Role,
        is_active: bool = True,
        tenant_id: UUID | None = None,
    ) -> User:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                INSERT INTO users (id, username, password_hash, role, tenant_id, is_active, created_at, updated_at)
                VALUES (:id, :username, :password_hash, :role, :tenant_id, :is_active, :created_at, :updated_at)
                ON CONFLICT (username) DO NOTHING
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "username": username,
                "password_hash": password_hash,
                "role": role,
                "tenant_id": str(tenant_id) if tenant_id else None,
                "is_active": is_active,
                "created_at": now,
                "updated_at": now,
            },
        ).mappings().first()
        if not row:
            raise ConflictError(f"username {username} already exists")
        return _to_user(row)

    def get_by_id(self, user_id: UUID) -> User | None:
        row = self.session.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {"id": str(user_id)},
        ).mappings().first()
        return _to_user(row) if row else None

    def get_by_username(self, username: str) -> User | None:
        row = self.session.execute(
            text("SELECT * FROM users WHERE username = :username"),
            {"username": username},
        ).mappings().first()
        return _to_user(row) if row else None

    def ensure_user(self, username: str, password_hash: str, role: Role, tenant_id: UUID | None = None) -> User:
        try:
            return self.create_user(
                username=username,
                password_hash=password_hash,
                role=role,
                is_active=True,
                tenant_id=tenant_id,
            )
        except ConflictError:
            pass
        existing = self.get_by_username(username)
        if not existing:
            raise NotFoundError(f"user {username} not found")
        return existing

    def list_users(
        self,
        limit: int,
        offset: int,
        role: Role | None,
        is_active: bool | None,
        username: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[User], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if role:
            conditions.append("role = :role")
            params["role"] = role
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active
        if username:
            conditions.append("username ILIKE :username")
            params["username"] = f"%{username}%"
        if tenant_id is not None:
            conditions.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self.session.execute(
            text(
                f"""
                SELECT * FROM users
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM users {where_clause}"),
            params,
        ).mappings().one()
        return ([_to_user(row) for row in rows], int(count_row["total"]))

    def update_user(
        self,
        user_id: UUID,
        role: Role | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
        tenant_id: UUID | None = None,
    ) -> User:
        row = self.session.execute(
            text(
                """
                UPDATE users
                SET role = COALESCE(:role, role),
                    tenant_id = CASE
                        WHEN COALESCE(:role, role) = 'admin' THEN NULL
                        WHEN CAST(:tenant_id AS UUID) IS NOT NULL THEN CAST(:tenant_id AS UUID)
                        ELSE tenant_id
                    END,
                    is_active = COALESCE(:is_active, is_active),
                    password_hash = COALESCE(:password_hash, password_hash),
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(user_id),
                "role": role,
                "tenant_id": str(tenant_id) if tenant_id else None,
                "is_active": is_active,
                "password_hash": password_hash,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"user {user_id} not found")
        return _to_user(row)

    def count_active_admins(self) -> int:
        row = self.session.execute(
            text("SELECT COUNT(*) AS total FROM users WHERE role = 'admin' AND is_active = true"),
        ).mappings().one()
        return int(row["total"])


class PostgresRefreshTokenRepository(RefreshTokenRepository):
    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: UUID, token_hash: str, expires_at) -> RefreshToken:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, revoked_at, created_at, updated_at)
                VALUES (:id, :user_id, :token_hash, :expires_at, NULL, :created_at, :updated_at)
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "user_id": str(user_id),
                "token_hash": token_hash,
                "expires_at": expires_at,
                "created_at": now,
                "updated_at": now,
            },
        ).mappings().one()
        return _to_refresh_token(row)

    def get_active_by_hash(self, token_hash: str) -> RefreshToken | None:
        row = self.session.execute(
            text(
                """
                SELECT *
                FROM refresh_tokens
                WHERE token_hash = :token_hash
                  AND revoked_at IS NULL
                  AND expires_at > :now
                """
            ),
            {"token_hash": token_hash, "now": datetime.now(timezone.utc)},
        ).mappings().first()
        return _to_refresh_token(row) if row else None

    def revoke_by_hash(self, token_hash: str) -> RefreshToken | None:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                UPDATE refresh_tokens
                SET revoked_at = COALESCE(revoked_at, :revoked_at),
                    updated_at = :updated_at
                WHERE token_hash = :token_hash
                RETURNING *
                """
            ),
            {
                "token_hash": token_hash,
                "revoked_at": now,
                "updated_at": now,
            },
        ).mappings().first()
        return _to_refresh_token(row) if row else None

    def revoke_all_for_user(self, user_id: UUID) -> int:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                WITH updated AS (
                    UPDATE refresh_tokens
                    SET revoked_at = COALESCE(revoked_at, :revoked_at),
                        updated_at = :updated_at
                    WHERE user_id = :user_id
                      AND revoked_at IS NULL
                    RETURNING 1
                )
                SELECT COUNT(*) AS total FROM updated
                """
            ),
            {
                "user_id": str(user_id),
                "revoked_at": now,
                "updated_at": now,
            },
        ).mappings().one()
        return int(row["total"])


class PostgresAuditLogRepository(AuditLogRepository):
    def __init__(self, session: Session):
        self.session = session

    def create(
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
        row = self.session.execute(
            text(
                """
                INSERT INTO audit_logs (
                    id, tenant_id, actor_user_id, actor_username, action, target_type, target_id,
                    request_id, ip_address, user_agent, metadata, created_at
                )
                VALUES (
                    :id, :tenant_id, :actor_user_id, :actor_username, :action, :target_type, :target_id,
                    :request_id, :ip_address, :user_agent, CAST(:metadata AS JSONB), :created_at
                )
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id) if tenant_id else None,
                "actor_user_id": str(actor_user_id) if actor_user_id else None,
                "actor_username": actor_username,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "request_id": str(request_id) if request_id else None,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "metadata": json.dumps(metadata or {}),
                "created_at": datetime.now(timezone.utc),
            },
        ).mappings().one()
        return _to_audit_log(row)

    def get(self, log_id: UUID) -> AuditLog | None:
        row = self.session.execute(
            text("SELECT * FROM audit_logs WHERE id = :id"),
            {"id": str(log_id)},
        ).mappings().first()
        return _to_audit_log(row) if row else None

    def list(
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
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if actor_user_id:
            conditions.append("actor_user_id = :actor_user_id")
            params["actor_user_id"] = str(actor_user_id)
        if action:
            conditions.append("action = :action")
            params["action"] = action
        if target_type:
            conditions.append("target_type = :target_type")
            params["target_type"] = target_type
        if request_id:
            conditions.append("request_id = :request_id")
            params["request_id"] = str(request_id)
        if tenant_id is not None:
            conditions.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self.session.execute(
            text(
                f"""
                SELECT *
                FROM audit_logs
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM audit_logs {where_clause}"),
            params,
        ).mappings().one()
        return ([_to_audit_log(row) for row in rows], int(count_row["total"]))


class PostgresTenantRepository(TenantRepository):
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, key: str, name: str, is_active: bool = True) -> Tenant:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                INSERT INTO tenants (id, key, name, is_active, created_at, updated_at)
                VALUES (:id, :key, :name, :is_active, :created_at, :updated_at)
                ON CONFLICT (key) DO NOTHING
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "key": key,
                "name": name,
                "is_active": is_active,
                "created_at": now,
                "updated_at": now,
            },
        ).mappings().first()
        if not row:
            raise ConflictError(f"tenant key {key} already exists")
        return _to_tenant(row)

    def get(self, tenant_id: UUID) -> Tenant | None:
        row = self.session.execute(
            text("SELECT * FROM tenants WHERE id = :id"),
            {"id": str(tenant_id)},
        ).mappings().first()
        return _to_tenant(row) if row else None

    def get_by_key(self, key: str) -> Tenant | None:
        row = self.session.execute(
            text("SELECT * FROM tenants WHERE key = :key"),
            {"key": key},
        ).mappings().first()
        return _to_tenant(row) if row else None

    def list(self, *, limit: int, offset: int, is_active: bool | None) -> tuple[list[Tenant], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self.session.execute(
            text(
                f"""
                SELECT *
                FROM tenants
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM tenants {where_clause}"),
            params,
        ).mappings().one()
        return ([_to_tenant(row) for row in rows], int(count_row["total"]))

    def update(self, tenant_id: UUID, *, name: str | None = None, is_active: bool | None = None) -> Tenant:
        row = self.session.execute(
            text(
                """
                UPDATE tenants
                SET name = COALESCE(:name, name),
                    is_active = COALESCE(:is_active, is_active),
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(tenant_id),
                "name": name,
                "is_active": is_active,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return _to_tenant(row)

    def delete(self, tenant_id: UUID) -> None:
        row = self.session.execute(
            text("DELETE FROM tenants WHERE id = :id RETURNING id"),
            {"id": str(tenant_id)},
        ).mappings().first()
        if not row:
            raise NotFoundError(f"tenant {tenant_id} not found")

    def count_active_users(self, tenant_id: UUID) -> int:
        row = self.session.execute(
            text(
                """
                SELECT COUNT(*) AS total
                FROM users
                WHERE tenant_id = :tenant_id
                  AND is_active = true
                """
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().one()
        return int(row["total"])

    def count_active_instances(self, tenant_id: UUID) -> int:
        row = self.session.execute(
            text(
                """
                SELECT COUNT(*) AS total
                FROM instances
                WHERE tenant_id = :tenant_id
                  AND status <> 'deleted'
                """
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().one()
        return int(row["total"])


class PostgresTenantQuotaRepository(TenantQuotaRepository):
    def __init__(self, session: Session):
        self.session = session

    def get(self, tenant_id: UUID) -> TenantQuota | None:
        row = self.session.execute(
            text("SELECT * FROM tenant_quotas WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
        return _to_tenant_quota(row) if row else None

    def upsert(
        self,
        tenant_id: UUID,
        *,
        max_instances: int,
        max_cpu: int,
        max_memory_mib: int,
        max_disk_gib: int,
    ) -> TenantQuota:
        row = self.session.execute(
            text(
                """
                INSERT INTO tenant_quotas (
                    tenant_id, max_instances, max_cpu, max_memory_mib, max_disk_gib, updated_at
                )
                VALUES (
                    :tenant_id, :max_instances, :max_cpu, :max_memory_mib, :max_disk_gib, :updated_at
                )
                ON CONFLICT (tenant_id) DO UPDATE
                SET max_instances = EXCLUDED.max_instances,
                    max_cpu = EXCLUDED.max_cpu,
                    max_memory_mib = EXCLUDED.max_memory_mib,
                    max_disk_gib = EXCLUDED.max_disk_gib,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "max_instances": max_instances,
                "max_cpu": max_cpu,
                "max_memory_mib": max_memory_mib,
                "max_disk_gib": max_disk_gib,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().one()
        return _to_tenant_quota(row)


class PostgresTenantUsageReadRepository(TenantUsageReadPort):
    def __init__(self, session: Session):
        self.session = session

    def get_usage(self, tenant_id: UUID) -> TenantUsage:
        row = self.session.execute(
            text(
                """
                SELECT
                    CAST(:tenant_id AS UUID) AS tenant_id,
                    COALESCE(v.used_instances, 0) AS used_instances,
                    COALESCE(v.used_cpu, 0) AS used_cpu,
                    COALESCE(v.used_memory_mib, 0) AS used_memory_mib,
                    COALESCE(v.used_disk_gib, 0) AS used_disk_gib
                FROM tenants t
                LEFT JOIN tenant_resource_usage_view v ON v.tenant_id = t.id
                WHERE t.id = :tenant_id
                """
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
        if not row:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return _to_tenant_usage(row)
