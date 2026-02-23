from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import NotFoundError
from app.domain.models import OutboxMessage
from app.ports import CommandOutboxRepository

from .common import to_outbox
from .orm.outbox import CommandOutboxModel


class PostgresCommandOutboxRepository(CommandOutboxRepository):
    def __init__(self, session: AsyncSession, notify_channel: str | None = None):
        self.session = session
        self.notify_channel = notify_channel

    async def enqueue_command(
        self,
        *,
        topic: str,
        payload: dict,
        task_id: UUID,
        request_id: UUID,
        max_attempts: int,
    ) -> OutboxMessage:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(CommandOutboxModel)
            .values(
                id=uuid4(),
                topic=topic,
                task_id=task_id,
                request_id=request_id,
                payload=payload,
                status="queued",
                attempt_count=0,
                max_attempts=max(1, int(max_attempts)),
                next_attempt_at=now,
                locked_by=None,
                lock_expires_at=None,
                last_error=None,
                sent_at=None,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[
                    CommandOutboxModel.task_id,
                    CommandOutboxModel.topic,
                    CommandOutboxModel.request_id,
                ],
                set_={"updated_at": now},
            )
            .returning(CommandOutboxModel)
        )
        model = await self.session.scalar(stmt)
        assert model is not None
        outbox = to_outbox(model)

        if self.notify_channel:
            await self.session.execute(
                select(func.pg_notify(self.notify_channel, str(outbox.id)))
            )
        return outbox

    async def claim_batch(
        self,
        *,
        locker_id: str,
        limit: int,
        lock_timeout_seconds: int,
    ) -> list[OutboxMessage]:
        now = datetime.now(timezone.utc)
        lock_expires_at = now + timedelta(seconds=max(1, int(lock_timeout_seconds)))

        picked = (
            select(CommandOutboxModel.id)
            .where(
                CommandOutboxModel.status == "queued",
                CommandOutboxModel.next_attempt_at <= now,
            )
            .order_by(CommandOutboxModel.created_at.asc())
            .limit(max(1, int(limit)))
            .with_for_update(skip_locked=True)
            .cte("picked")
        )
        stmt = (
            update(CommandOutboxModel)
            .where(CommandOutboxModel.id.in_(select(picked.c.id)))
            .values(
                status="publishing",
                locked_by=locker_id,
                lock_expires_at=lock_expires_at,
                updated_at=now,
            )
            .returning(CommandOutboxModel)
        )
        models = (await self.session.scalars(stmt)).all()
        return [to_outbox(model) for model in models]

    async def mark_sent(self, message_id: UUID) -> OutboxMessage:
        now = datetime.now(timezone.utc)
        stmt = (
            update(CommandOutboxModel)
            .where(CommandOutboxModel.id == message_id)
            .values(
                status="sent",
                sent_at=now,
                locked_by=None,
                lock_expires_at=None,
                last_error=None,
                updated_at=now,
            )
            .returning(CommandOutboxModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"outbox message {message_id} not found")
        return to_outbox(model)

    async def mark_retry(
        self, message_id: UUID, *, delay_seconds: int, error_message: str | None
    ) -> OutboxMessage:
        now = datetime.now(timezone.utc)
        next_attempt_at = now + timedelta(seconds=max(1, int(delay_seconds)))
        stmt = (
            update(CommandOutboxModel)
            .where(CommandOutboxModel.id == message_id)
            .values(
                status="queued",
                attempt_count=CommandOutboxModel.attempt_count + 1,
                next_attempt_at=next_attempt_at,
                locked_by=None,
                lock_expires_at=None,
                last_error=error_message,
                updated_at=now,
            )
            .returning(CommandOutboxModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"outbox message {message_id} not found")
        return to_outbox(model)

    async def mark_failed(
        self, message_id: UUID, *, error_message: str | None
    ) -> OutboxMessage:
        now = datetime.now(timezone.utc)
        stmt = (
            update(CommandOutboxModel)
            .where(CommandOutboxModel.id == message_id)
            .values(
                status="failed",
                attempt_count=CommandOutboxModel.attempt_count + 1,
                locked_by=None,
                lock_expires_at=None,
                last_error=error_message,
                updated_at=now,
            )
            .returning(CommandOutboxModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"outbox message {message_id} not found")
        return to_outbox(model)

    async def recover_stuck_publishing(self) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            update(CommandOutboxModel)
            .where(
                CommandOutboxModel.status == "publishing",
                CommandOutboxModel.lock_expires_at.is_not(None),
                CommandOutboxModel.lock_expires_at < now,
            )
            .values(
                status="queued",
                locked_by=None,
                lock_expires_at=None,
                next_attempt_at=now,
                updated_at=now,
            )
            .returning(CommandOutboxModel.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return len(rows)
