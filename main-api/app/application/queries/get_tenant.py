from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID
from app.domain.errors import TenantNotFoundError
from app.domain.models import Tenant, TenantQuota
from app.ports import TenantQuotaRepository, TenantRepository


@dataclass(frozen=True)
class TenantDetail:
    tenant: Tenant
    quota: TenantQuota | None


class GetTenantHandler:
    def __init__(
        self,
        tenant_repository: TenantRepository,
        tenant_quota_repository: TenantQuotaRepository,
    ):
        self.tenant_repository = tenant_repository
        self.tenant_quota_repository = tenant_quota_repository

    async def handle(self, tenant_id: UUID) -> TenantDetail:
        tenant = await self.tenant_repository.get(tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"tenant {tenant_id} not found")
        return TenantDetail(
            tenant=tenant,
            quota=await self.tenant_quota_repository.get(tenant_id),
        )
