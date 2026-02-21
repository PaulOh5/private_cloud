from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import Tenant, TenantQuota, TenantUsage
from app.ports import TenantQuotaRepository, TenantRepository, TenantUsageReadPort

from .common import _to_tenant, _to_tenant_quota, _to_tenant_usage


class PostgresTenantRepository(TenantRepository):
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, key: str, name: str, is_active: bool = True) -> Tenant:
        now = datetime.now(timezone.utc)
        row = self.session.execute(
            text(
                """
                INSERT INTO tenants (id, key, name, is_active, created_at, updated_at)
                VALUES (:id, :key, :name, :is_active, :created_at, :updated_at)
                ON CONFLICT (key) DO NOTHING
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "key": key,
                "name": name,
                "is_active": is_active,
                "created_at": now,
                "updated_at": now,
            },
        ).mappings().first()
        if not row:
            raise ConflictError(f"tenant key {key} already exists")
        return _to_tenant(row)

    def get(self, tenant_id: UUID) -> Tenant | None:
        row = self.session.execute(
            text("SELECT * FROM tenants WHERE id = :id"),
            {"id": str(tenant_id)},
        ).mappings().first()
        return _to_tenant(row) if row else None

    def get_by_key(self, key: str) -> Tenant | None:
        row = self.session.execute(
            text("SELECT * FROM tenants WHERE key = :key"),
            {"key": key},
        ).mappings().first()
        return _to_tenant(row) if row else None

    def list(self, *, limit: int, offset: int, is_active: bool | None) -> tuple[list[Tenant], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self.session.execute(
            text(
                f"""
                SELECT *
                FROM tenants
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM tenants {where_clause}"),
            params,
        ).mappings().one()
        return ([_to_tenant(row) for row in rows], int(count_row["total"]))

    def update(self, tenant_id: UUID, *, name: str | None = None, is_active: bool | None = None) -> Tenant:
        row = self.session.execute(
            text(
                """
                UPDATE tenants
                SET name = COALESCE(:name, name),
                    is_active = COALESCE(:is_active, is_active),
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(tenant_id),
                "name": name,
                "is_active": is_active,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return _to_tenant(row)

    def delete(self, tenant_id: UUID) -> None:
        row = self.session.execute(
            text("DELETE FROM tenants WHERE id = :id RETURNING id"),
            {"id": str(tenant_id)},
        ).mappings().first()
        if not row:
            raise NotFoundError(f"tenant {tenant_id} not found")

    def count_active_users(self, tenant_id: UUID) -> int:
        row = self.session.execute(
            text(
                """
                SELECT COUNT(*) AS total
                FROM users
                WHERE tenant_id = :tenant_id
                  AND is_active = true
                """
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().one()
        return int(row["total"])

    def count_active_instances(self, tenant_id: UUID) -> int:
        row = self.session.execute(
            text(
                """
                SELECT COUNT(*) AS total
                FROM instances
                WHERE tenant_id = :tenant_id
                  AND status <> 'deleted'
                """
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().one()
        return int(row["total"])


class PostgresTenantQuotaRepository(TenantQuotaRepository):
    def __init__(self, session: Session):
        self.session = session

    def get(self, tenant_id: UUID) -> TenantQuota | None:
        row = self.session.execute(
            text("SELECT * FROM tenant_quotas WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
        return _to_tenant_quota(row) if row else None

    def upsert(
        self,
        tenant_id: UUID,
        *,
        max_instances: int,
        max_cpu: int,
        max_memory_mib: int,
        max_disk_gib: int,
    ) -> TenantQuota:
        row = self.session.execute(
            text(
                """
                INSERT INTO tenant_quotas (
                    tenant_id, max_instances, max_cpu, max_memory_mib, max_disk_gib, updated_at
                )
                VALUES (
                    :tenant_id, :max_instances, :max_cpu, :max_memory_mib, :max_disk_gib, :updated_at
                )
                ON CONFLICT (tenant_id) DO UPDATE
                SET max_instances = EXCLUDED.max_instances,
                    max_cpu = EXCLUDED.max_cpu,
                    max_memory_mib = EXCLUDED.max_memory_mib,
                    max_disk_gib = EXCLUDED.max_disk_gib,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "max_instances": max_instances,
                "max_cpu": max_cpu,
                "max_memory_mib": max_memory_mib,
                "max_disk_gib": max_disk_gib,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().one()
        return _to_tenant_quota(row)


class PostgresTenantUsageReadRepository(TenantUsageReadPort):
    def __init__(self, session: Session):
        self.session = session

    def get_usage(self, tenant_id: UUID) -> TenantUsage:
        row = self.session.execute(
            text(
                """
                SELECT
                    CAST(:tenant_id AS UUID) AS tenant_id,
                    COALESCE(v.used_instances, 0) AS used_instances,
                    COALESCE(v.used_cpu, 0) AS used_cpu,
                    COALESCE(v.used_memory_mib, 0) AS used_memory_mib,
                    COALESCE(v.used_disk_gib, 0) AS used_disk_gib
                FROM tenants t
                LEFT JOIN tenant_resource_usage_view v ON v.tenant_id = t.id
                WHERE t.id = :tenant_id
                """
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
        if not row:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return _to_tenant_usage(row)
