from __future__ import annotations

from uuid import UUID

from app.domain.models import TenantUsage
from app.ports import TenantUsageReadPort


class GetTenantUsageHandler:
    def __init__(self, tenant_usage_read_port: TenantUsageReadPort):
        self.tenant_usage_read_port = tenant_usage_read_port

    def handle(self, tenant_id: UUID) -> TenantUsage:
        return self.tenant_usage_read_port.get_usage(tenant_id)
