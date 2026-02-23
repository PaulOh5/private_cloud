from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.postgres_repositories.orm.resource import (
    ResourceCapacityModel,
    resource_reservations_view,
    tenant_resource_usage_view,
)
from app.adapters.postgres_repositories.orm.tenant import TenantModel, TenantQuotaModel
from app.domain.errors import (
    CapacityExceededError,
    QuotaExceededError,
    TenantInactiveError,
)
from app.ports import CapacityCheckInput, TenantQuotaCheckInput


def _profile_factors(profile: str) -> tuple[int, int, int, int]:
    if profile == "none":
        return (0, 0, 0, 0)
    if profile == "stopped":
        return (1, 0, 0, 1)
    if profile == "running":
        return (1, 1, 1, 1)
    raise ValueError(f"invalid resource profile: {profile}")


class HostResourceAccountingAdapter:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def assert_capacity(self, check: CapacityCheckInput) -> None:
        usage_stmt = (
            select(
                func.coalesce(resource_reservations_view.c.reserved_cpu, 0).label(
                    "reserved_cpu"
                ),
                func.coalesce(
                    resource_reservations_view.c.reserved_memory_mib, 0
                ).label("reserved_memory_mib"),
                func.coalesce(resource_reservations_view.c.reserved_disk_gib, 0).label(
                    "reserved_disk_gib"
                ),
            )
            .select_from(resource_reservations_view)
            .where(resource_reservations_view.c.host_node == check.host_node)
        )
        usage_row = (await self.session.execute(usage_stmt)).one_or_none()
        capacity = await self.session.execute(
            select(
                ResourceCapacityModel.total_cpu,
                ResourceCapacityModel.total_memory_mib,
                ResourceCapacityModel.total_disk_gib,
            ).where(ResourceCapacityModel.host_node == check.host_node)
        )
        cap = capacity.one_or_none()

        if not cap:
            raise CapacityExceededError(
                f"resource capacity for host {check.host_node} not configured"
            )

        reserved_cpu = int(getattr(usage_row, "reserved_cpu", 0))
        reserved_mem = int(getattr(usage_row, "reserved_memory_mib", 0))
        reserved_disk = int(getattr(usage_row, "reserved_disk_gib", 0))

        _, current_cpu_factor, current_mem_factor, current_disk_factor = (
            _profile_factors(check.current_profile)
        )
        _, requested_cpu_factor, requested_mem_factor, requested_disk_factor = (
            _profile_factors(check.requested_profile)
        )

        current_cpu = (check.current.cpu if check.current else 0) * current_cpu_factor
        current_mem = (
            check.current.memory_mib if check.current else 0
        ) * current_mem_factor
        current_disk = (
            check.current.disk_gib if check.current else 0
        ) * current_disk_factor

        requested_cpu = check.requested.cpu * requested_cpu_factor
        requested_mem = check.requested.memory_mib * requested_mem_factor
        requested_disk = check.requested.disk_gib * requested_disk_factor

        next_cpu = reserved_cpu - current_cpu + requested_cpu
        next_mem = reserved_mem - current_mem + requested_mem
        next_disk = reserved_disk - current_disk + requested_disk

        if next_cpu > int(cap.total_cpu):
            raise CapacityExceededError("cpu capacity exceeded")
        if next_mem > int(cap.total_memory_mib):
            raise CapacityExceededError("memory capacity exceeded")
        if next_disk > int(cap.total_disk_gib):
            raise CapacityExceededError("disk capacity exceeded")


class TenantQuotaAccountingAdapter:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def assert_quota(self, check: TenantQuotaCheckInput) -> None:
        usage_join_stmt = (
            select(
                TenantModel.id,
                TenantModel.is_active,
                TenantQuotaModel.max_instances,
                TenantQuotaModel.max_cpu,
                TenantQuotaModel.max_memory_mib,
                TenantQuotaModel.max_disk_gib,
                func.coalesce(tenant_resource_usage_view.c.used_instances, 0).label(
                    "used_instances"
                ),
                func.coalesce(tenant_resource_usage_view.c.used_cpu, 0).label(
                    "used_cpu"
                ),
                func.coalesce(tenant_resource_usage_view.c.used_memory_mib, 0).label(
                    "used_memory_mib"
                ),
                func.coalesce(tenant_resource_usage_view.c.used_disk_gib, 0).label(
                    "used_disk_gib"
                ),
            )
            .select_from(TenantModel)
            .outerjoin(TenantQuotaModel, TenantQuotaModel.tenant_id == TenantModel.id)
            .outerjoin(
                tenant_resource_usage_view,
                tenant_resource_usage_view.c.tenant_id == TenantModel.id,
            )
            .where(TenantModel.id == check.tenant_id)
        )
        row = (await self.session.execute(usage_join_stmt)).one_or_none()

        if not row:
            raise QuotaExceededError(f"tenant {check.tenant_id} not found")
        if not bool(row.is_active):
            raise TenantInactiveError(f"tenant {check.tenant_id} is inactive")
        if row.max_instances is None:
            raise QuotaExceededError(
                f"tenant quota for {check.tenant_id} not configured"
            )

        (
            current_instance_factor,
            current_cpu_factor,
            current_mem_factor,
            current_disk_factor,
        ) = _profile_factors(check.current_profile)
        (
            requested_instance_factor,
            requested_cpu_factor,
            requested_mem_factor,
            requested_disk_factor,
        ) = _profile_factors(check.requested_profile)

        current_instances = current_instance_factor if check.current else 0
        requested_instances = requested_instance_factor

        current_cpu = (check.current.cpu if check.current else 0) * current_cpu_factor
        current_mem = (
            check.current.memory_mib if check.current else 0
        ) * current_mem_factor
        current_disk = (
            check.current.disk_gib if check.current else 0
        ) * current_disk_factor

        requested_cpu = check.requested.cpu * requested_cpu_factor
        requested_mem = check.requested.memory_mib * requested_mem_factor
        requested_disk = check.requested.disk_gib * requested_disk_factor

        next_instances = (
            int(row.used_instances) - current_instances + requested_instances
        )
        next_cpu = int(row.used_cpu) - current_cpu + requested_cpu
        next_mem = int(row.used_memory_mib) - current_mem + requested_mem
        next_disk = int(row.used_disk_gib) - current_disk + requested_disk

        if next_instances > int(row.max_instances):
            raise QuotaExceededError("instance quota exceeded")
        if next_cpu > int(row.max_cpu):
            raise QuotaExceededError("cpu quota exceeded")
        if next_mem > int(row.max_memory_mib):
            raise QuotaExceededError("memory quota exceeded")
        if next_disk > int(row.max_disk_gib):
            raise QuotaExceededError("disk quota exceeded")
