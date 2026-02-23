from __future__ import annotations

from datetime import datetime
from typing import Any, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (
    TASK_COMMAND_ENUM_TYPE,
    TASK_STATUS_ENUM_TYPE,
    TaskCommandEnum,
    TaskStatusEnum,
)

if TYPE_CHECKING:
    from .instance import InstanceModel


class InstanceTaskModel(Base):
    __tablename__ = "instance_tasks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    instance_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("instances.id"), nullable=False
    )
    command: Mapped[TaskCommandEnum] = mapped_column(
        TASK_COMMAND_ENUM_TYPE, nullable=False
    )
    status: Mapped[TaskStatusEnum] = mapped_column(
        TASK_STATUS_ENUM_TYPE, nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, unique=True
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_of_task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    canceled_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    instance: Mapped[InstanceModel] = relationship(back_populates="tasks")
