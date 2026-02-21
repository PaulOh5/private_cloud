from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.errors import NotFoundError
from app.domain.models import OutboxMessage
from app.ports import CommandOutboxRepository

from .common import _to_outbox


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


