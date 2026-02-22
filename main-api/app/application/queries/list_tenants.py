from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import Tenant, TenantQuota
from app.ports import TenantQuotaRepository, TenantRepository


@dataclass(frozen=True)
class ListTenantsQuery:
    limit: int
    offset: int
    is_active: bool | None = None


@dataclass(frozen=True)
class TenantWithQuota:
    tenant: Tenant
    quota: TenantQuota | None


@dataclass(frozen=True)
class ListTenantsResult:
    items: list[TenantWithQuota]
    total: int


class ListTenantsHandler:
    def __init__(self, tenant_repository: TenantRepository, tenant_quota_repository: TenantQuotaRepository):
        self.tenant_repository = tenant_repository
        self.tenant_quota_repository = tenant_quota_repository

    def handle(self, query: ListTenantsQuery) -> ListTenantsResult:
        tenants, total = self.tenant_repository.list(
            limit=query.limit,
            offset=query.offset,
            is_active=query.is_active,
        )
        items = [
            TenantWithQuota(
                tenant=tenant,
                quota=self.tenant_quota_repository.get(tenant.id),
            )
            for tenant in tenants
        ]
        return ListTenantsResult(items=items, total=total)
