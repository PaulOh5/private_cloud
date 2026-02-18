from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.errors import CapacityExceededError, QuotaExceededError, TenantInactiveError
from app.ports.interfaces import CapacityCheckInput, TenantQuotaCheckInput


def _profile_factors(profile: str) -> tuple[int, int, int, int]:
    if profile == "none":
        return (0, 0, 0, 0)
    if profile == "stopped":
        return (1, 0, 0, 1)
    if profile == "running":
        return (1, 1, 1, 1)
    raise ValueError(f"invalid resource profile: {profile}")


class HostResourceAccountingAdapter:
    def __init__(self, session: Session):
        self.session = session

    def assert_capacity(self, check: CapacityCheckInput) -> None:
        row = self.session.execute(
            text(
                """
                SELECT
                    c.total_cpu,
                    c.total_memory_mib,
                    c.total_disk_gib,
                    COALESCE(v.reserved_cpu, 0) AS reserved_cpu,
                    COALESCE(v.reserved_memory_mib, 0) AS reserved_memory_mib,
                    COALESCE(v.reserved_disk_gib, 0) AS reserved_disk_gib
                FROM resource_capacity c
                LEFT JOIN resource_reservations_view v ON v.host_node = c.host_node
                WHERE c.host_node = :host_node
                """
            ),
            {"host_node": check.host_node},
        ).mappings().first()

        if not row:
            raise CapacityExceededError(f"resource capacity for host {check.host_node} not configured")

        _, current_cpu_factor, current_mem_factor, current_disk_factor = _profile_factors(check.current_profile)
        _, requested_cpu_factor, requested_mem_factor, requested_disk_factor = _profile_factors(check.requested_profile)

        current_cpu = (check.current.cpu if check.current else 0) * current_cpu_factor
        current_mem = (check.current.memory_mib if check.current else 0) * current_mem_factor
        current_disk = (check.current.disk_gib if check.current else 0) * current_disk_factor

        requested_cpu = check.requested.cpu * requested_cpu_factor
        requested_mem = check.requested.memory_mib * requested_mem_factor
        requested_disk = check.requested.disk_gib * requested_disk_factor

        next_cpu = int(row["reserved_cpu"]) - current_cpu + requested_cpu
        next_mem = int(row["reserved_memory_mib"]) - current_mem + requested_mem
        next_disk = int(row["reserved_disk_gib"]) - current_disk + requested_disk

        if next_cpu > int(row["total_cpu"]):
            raise CapacityExceededError("cpu capacity exceeded")
        if next_mem > int(row["total_memory_mib"]):
            raise CapacityExceededError("memory capacity exceeded")
        if next_disk > int(row["total_disk_gib"]):
            raise CapacityExceededError("disk capacity exceeded")


class TenantQuotaAccountingAdapter:
    def __init__(self, session: Session):
        self.session = session

    def assert_quota(self, check: TenantQuotaCheckInput) -> None:
        row = self.session.execute(
            text(
                """
                SELECT
                    t.id,
                    t.is_active,
                    q.max_instances,
                    q.max_cpu,
                    q.max_memory_mib,
                    q.max_disk_gib,
                    COALESCE(u.used_instances, 0) AS used_instances,
                    COALESCE(u.used_cpu, 0) AS used_cpu,
                    COALESCE(u.used_memory_mib, 0) AS used_memory_mib,
                    COALESCE(u.used_disk_gib, 0) AS used_disk_gib
                FROM tenants t
                LEFT JOIN tenant_quotas q ON q.tenant_id = t.id
                LEFT JOIN tenant_resource_usage_view u ON u.tenant_id = t.id
                WHERE t.id = :tenant_id
                """
            ),
            {"tenant_id": str(check.tenant_id)},
        ).mappings().first()

        if not row:
            raise QuotaExceededError(f"tenant {check.tenant_id} not found")
        if not bool(row["is_active"]):
            raise TenantInactiveError(f"tenant {check.tenant_id} is inactive")
        if row["max_instances"] is None:
            raise QuotaExceededError(f"tenant quota for {check.tenant_id} not configured")

        current_instance_factor, current_cpu_factor, current_mem_factor, current_disk_factor = _profile_factors(
            check.current_profile
        )
        requested_instance_factor, requested_cpu_factor, requested_mem_factor, requested_disk_factor = _profile_factors(
            check.requested_profile
        )

        current_instances = current_instance_factor if check.current else 0
        requested_instances = requested_instance_factor

        current_cpu = (check.current.cpu if check.current else 0) * current_cpu_factor
        current_mem = (check.current.memory_mib if check.current else 0) * current_mem_factor
        current_disk = (check.current.disk_gib if check.current else 0) * current_disk_factor

        requested_cpu = check.requested.cpu * requested_cpu_factor
        requested_mem = check.requested.memory_mib * requested_mem_factor
        requested_disk = check.requested.disk_gib * requested_disk_factor

        next_instances = int(row["used_instances"]) - current_instances + requested_instances
        next_cpu = int(row["used_cpu"]) - current_cpu + requested_cpu
        next_mem = int(row["used_memory_mib"]) - current_mem + requested_mem
        next_disk = int(row["used_disk_gib"]) - current_disk + requested_disk

        if next_instances > int(row["max_instances"]):
            raise QuotaExceededError("instance quota exceeded")
        if next_cpu > int(row["max_cpu"]):
            raise QuotaExceededError("cpu quota exceeded")
        if next_mem > int(row["max_memory_mib"]):
            raise QuotaExceededError("memory quota exceeded")
        if next_disk > int(row["max_disk_gib"]):
            raise QuotaExceededError("disk quota exceeded")
