from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .enums import OUTBOX_STATUS_ENUM_TYPE, OutboxStatusEnum


class CommandOutboxModel(Base):
    __tablename__ = "command_outbox"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "topic",
            "request_id",
            name="command_outbox_task_topic_request_idx",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxStatusEnum] = mapped_column(
        OUTBOX_STATUS_ENUM_TYPE, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    locked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
