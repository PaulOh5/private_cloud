from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.models import Tenant, TenantQuota, TenantUsage


class TenantRepository(ABC):
    @abstractmethod
    def create(self, *, key: str, name: str, is_active: bool = True) -> Tenant:
        raise NotImplementedError

    @abstractmethod
    def get(self, tenant_id: UUID) -> Tenant | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_key(self, key: str) -> Tenant | None:
        raise NotImplementedError

    @abstractmethod
    def list(self, *, limit: int, offset: int, is_active: bool | None) -> tuple[list[Tenant], int]:
        raise NotImplementedError

    @abstractmethod
    def update(self, tenant_id: UUID, *, name: str | None = None, is_active: bool | None = None) -> Tenant:
        raise NotImplementedError

    @abstractmethod
    def delete(self, tenant_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    def count_active_users(self, tenant_id: UUID) -> int:
        raise NotImplementedError

    @abstractmethod
    def count_active_instances(self, tenant_id: UUID) -> int:
        raise NotImplementedError


class TenantQuotaRepository(ABC):
    @abstractmethod
    def get(self, tenant_id: UUID) -> TenantQuota | None:
        raise NotImplementedError

    @abstractmethod
    def upsert(
        self,
        tenant_id: UUID,
        *,
        max_instances: int,
        max_cpu: int,
        max_memory_mib: int,
        max_disk_gib: int,
    ) -> TenantQuota:
        raise NotImplementedError


class TenantUsageReadPort(ABC):
    @abstractmethod
    def get_usage(self, tenant_id: UUID) -> TenantUsage:
        raise NotImplementedError
