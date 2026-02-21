from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.errors import NotFoundError
from app.domain.models import InstanceTask
from app.ports import TaskRepository

from .common import _to_task


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


