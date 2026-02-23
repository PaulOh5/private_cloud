from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import INET, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import INSTANCE_STATUS_ENUM_TYPE, InstanceStatusEnum

if TYPE_CHECKING:
    from .task import InstanceTaskModel
    from .tenant import TenantModel


class InstanceModel(Base):
    __tablename__ = "instances"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    cpu: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_mib: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_gib: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[InstanceStatusEnum] = mapped_column(
        INSTANCE_STATUS_ENUM_TYPE, nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    host_node: Mapped[str] = mapped_column(String, nullable=False)
    reserve_resources: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    last_task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    tenant: Mapped[TenantModel] = relationship(back_populates="instances")
    tasks: Mapped[list[InstanceTaskModel]] = relationship(back_populates="instance")
