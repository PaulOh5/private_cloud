from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.auth import RefreshToken, Role, User
from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import AuditLog, Instance, InstanceTask, ResourceSpec
from app.ports.interfaces import (
    AuditLogRepository,
    InstanceReadRepository,
    InstanceRepository,
    RefreshTokenRepository,
    TaskRepository,
    UserRepository,
)


def _to_instance(row) -> Instance:
    return Instance(
        id=row["id"],
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


def _to_user(row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        role=row["role"],
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
                    id, name, cpu, memory_mib, disk_gib,
                    status, ip_address, host_node, reserve_resources,
                    last_task_id, deleted_at, created_at, updated_at
                )
                VALUES (
                    :id, :name, :cpu, :memory_mib, :disk_gib,
                    :status, :ip_address, :host_node, :reserve_resources,
                    :last_task_id, :deleted_at, :created_at, :updated_at
                )
                RETURNING *
                """
            ),
            {
                "id": str(instance.id),
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

    def get(self, instance_id: UUID) -> Instance | None:
        row = self.session.execute(
            text("SELECT * FROM instances WHERE id = :id"),
            {"id": str(instance_id)},
        ).mappings().first()
        return _to_instance(row) if row else None

    def list(self, limit: int, offset: int, status: str | None, name: str | None) -> tuple[list[Instance], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if name:
            conditions.append("name ILIKE :name")
            params["name"] = f"%{name}%"

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
                      AND status IN ('queued', 'running')
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
                    attempt_count, max_attempts,
                    created_at, started_at, finished_at, updated_at
                )
                VALUES (
                    :id, :instance_id, :command, :status, :request_id,
                    CAST(:request_payload AS JSONB), CAST(:result_payload AS JSONB),
                    :error_code, :error_message,
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
                "result_payload": json.dumps(task.result_payload) if task.result_payload else None,
                "error_code": task.error_code,
                "error_message": task.error_message,
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
    ) -> tuple[list[InstanceTask], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if instance_id:
            conditions.append("instance_id = :instance_id")
            params["instance_id"] = str(instance_id)
        if command:
            conditions.append("command = :command")
            params["command"] = command

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self.session.execute(
            text(
                f"""
                SELECT * FROM instance_tasks
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()

        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM instance_tasks {where_clause}"),
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
                "result_payload": json.dumps(result_payload) if result_payload else None,
                "error_code": error_code,
                "error_message": error_message,
                "finished_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"task {task_id} not found")
        return _to_task(row)


class PostgresUserRepository(UserRepository):
    def __init__(self, session: Session):
        self.session = session

    def create_user(self, username: str, password_hash: str, role: Role, is_active: bool = True) -> User:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                INSERT INTO users (id, username, password_hash, role, is_active, created_at, updated_at)
                VALUES (:id, :username, :password_hash, :role, :is_active, :created_at, :updated_at)
                ON CONFLICT (username) DO NOTHING
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "username": username,
                "password_hash": password_hash,
                "role": role,
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

    def ensure_user(self, username: str, password_hash: str, role: Role) -> User:
        try:
            return self.create_user(username=username, password_hash=password_hash, role=role, is_active=True)
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
    ) -> User:
        row = self.session.execute(
            text(
                """
                UPDATE users
                SET role = COALESCE(:role, role),
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
                    id, actor_user_id, actor_username, action, target_type, target_id,
                    request_id, ip_address, user_agent, metadata, created_at
                )
                VALUES (
                    :id, :actor_user_id, :actor_username, :action, :target_type, :target_id,
                    :request_id, :ip_address, :user_agent, CAST(:metadata AS JSONB), :created_at
                )
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
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
