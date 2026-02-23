from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .auth import UserModel
    from .audit import AuditLogModel
    from .instance import InstanceModel


class TenantModel(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    quota: Mapped[TenantQuotaModel | None] = relationship(
        back_populates="tenant", uselist=False
    )
    instances: Mapped[list[InstanceModel]] = relationship(back_populates="tenant")
    users: Mapped[list[UserModel]] = relationship(back_populates="tenant")
    audit_logs: Mapped[list[AuditLogModel]] = relationship(back_populates="tenant")


class TenantQuotaModel(Base):
    __tablename__ = "tenant_quotas"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    max_instances: Mapped[int] = mapped_column(Integer, nullable=False)
    max_cpu: Mapped[int] = mapped_column(Integer, nullable=False)
    max_memory_mib: Mapped[int] = mapped_column(Integer, nullable=False)
    max_disk_gib: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    tenant: Mapped[TenantModel] = relationship(back_populates="quota")
