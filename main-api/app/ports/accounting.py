from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.domain.models import ResourceSpec


@dataclass(frozen=True)
class CapacityCheckInput:
    host_node: str
    current: ResourceSpec | None
    requested: ResourceSpec
    current_profile: Literal["running", "stopped", "none"] = "running"
    requested_profile: Literal["running", "stopped", "none"] = "running"


class ResourceAccountingPort(Protocol):
    def assert_capacity(self, check: CapacityCheckInput) -> None:
        ...


@dataclass(frozen=True)
class TenantQuotaCheckInput:
    tenant_id: UUID
    current: ResourceSpec | None
    requested: ResourceSpec
    current_profile: Literal["running", "stopped", "none"] = "running"
    requested_profile: Literal["running", "stopped", "none"] = "running"


class TenantQuotaAccountingPort(Protocol):
    def assert_quota(self, check: TenantQuotaCheckInput) -> None:
        ...
