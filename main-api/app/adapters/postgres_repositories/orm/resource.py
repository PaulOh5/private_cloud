from __future__ import annotations

from sqlalchemy import Column, Integer, String, Table
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ResourceCapacityModel(Base):
    __tablename__ = "resource_capacity"

    host_node: Mapped[str] = mapped_column(String, primary_key=True)
    total_cpu: Mapped[int] = mapped_column(Integer, nullable=False)
    total_memory_mib: Mapped[int] = mapped_column(Integer, nullable=False)
    total_disk_gib: Mapped[int] = mapped_column(Integer, nullable=False)


resource_reservations_view = Table(
    "resource_reservations_view",
    Base.metadata,
    Column("host_node", String),
    Column("reserved_cpu", Integer),
    Column("reserved_memory_mib", Integer),
    Column("reserved_disk_gib", Integer),
)


tenant_resource_usage_view = Table(
    "tenant_resource_usage_view",
    Base.metadata,
    Column("tenant_id", PGUUID(as_uuid=True)),
    Column("used_instances", Integer),
    Column("used_cpu", Integer),
    Column("used_memory_mib", Integer),
    Column("used_disk_gib", Integer),
)
