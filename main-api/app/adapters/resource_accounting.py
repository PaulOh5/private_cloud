from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.errors import CapacityExceededError
from app.ports.interfaces import CapacityCheckInput


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

        current_cpu = check.current.cpu if check.current else 0
        current_mem = check.current.memory_mib if check.current else 0
        current_disk = check.current.disk_gib if check.current else 0

        next_cpu = int(row["reserved_cpu"]) - current_cpu + check.requested.cpu
        next_mem = int(row["reserved_memory_mib"]) - current_mem + check.requested.memory_mib
        next_disk = int(row["reserved_disk_gib"]) - current_disk + check.requested.disk_gib

        if next_cpu > int(row["total_cpu"]):
            raise CapacityExceededError("cpu capacity exceeded")
        if next_mem > int(row["total_memory_mib"]):
            raise CapacityExceededError("memory capacity exceeded")
        if next_disk > int(row["total_disk_gib"]):
            raise CapacityExceededError("disk capacity exceeded")
