from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.errors import NotFoundError
from app.domain.models import Instance, ResourceSpec
from app.ports import InstanceReadRepository, InstanceRepository

from .common import _to_instance


class PostgresInstanceRepository(InstanceRepository):
    def __init__(self, session: Session):
        self.session = session

    def get_for_update(self, instance_id: UUID) -> Instance | None:
        row = self.session.execute(
            text("SELECT * FROM instances WHERE id = :id FOR UPDATE"),
            {"id": str(instance_id)},
        ).mappings().first()
        return _to_instance(row) if row else None

    def create(self, instance: Instance) -> Instance:
        row = self.session.execute(
            text(
                """
                INSERT INTO instances (
                    id, tenant_id, name, cpu, memory_mib, disk_gib,
                    status, ip_address, host_node, reserve_resources,
                    last_task_id, deleted_at, created_at, updated_at
                )
                VALUES (
                    :id, :tenant_id, :name, :cpu, :memory_mib, :disk_gib,
                    :status, :ip_address, :host_node, :reserve_resources,
                    :last_task_id, :deleted_at, :created_at, :updated_at
                )
                RETURNING *
                """
            ),
            {
                "id": str(instance.id),
                "tenant_id": str(instance.tenant_id),
                "name": instance.name,
                "cpu": instance.resource_spec.cpu,
                "memory_mib": instance.resource_spec.memory_mib,
                "disk_gib": instance.resource_spec.disk_gib,
                "status": instance.status,
                "ip_address": instance.ip_address,
                "host_node": instance.host_node,
                "reserve_resources": instance.reserve_resources,
                "last_task_id": str(instance.last_task_id) if instance.last_task_id else None,
                "deleted_at": instance.deleted_at,
                "created_at": instance.created_at,
                "updated_at": instance.updated_at,
            },
        ).mappings().one()
        return _to_instance(row)

    def update_spec(
        self,
        instance_id: UUID,
        spec: ResourceSpec,
        status: str,
        ip_address: str | None,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
    ) -> Instance:
        row = self.session.execute(
            text(
                """
                UPDATE instances
                SET cpu = :cpu,
                    memory_mib = :memory_mib,
                    disk_gib = :disk_gib,
                    status = :status,
                    ip_address = :ip_address,
                    reserve_resources = :reserve_resources,
                    last_task_id = :last_task_id,
                    deleted_at = :deleted_at,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(instance_id),
                "cpu": spec.cpu,
                "memory_mib": spec.memory_mib,
                "disk_gib": spec.disk_gib,
                "status": status,
                "ip_address": ip_address,
                "reserve_resources": reserve_resources,
                "last_task_id": str(last_task_id) if last_task_id else None,
                "deleted_at": deleted_at,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"instance {instance_id} not found")
        return _to_instance(row)

    def update_state(
        self,
        instance_id: UUID,
        status: str,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
        ip_address: str | None,
    ) -> Instance:
        row = self.session.execute(
            text(
                """
                UPDATE instances
                SET status = :status,
                    reserve_resources = :reserve_resources,
                    last_task_id = :last_task_id,
                    deleted_at = :deleted_at,
                    ip_address = :ip_address,
                    updated_at = :updated_at
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(instance_id),
                "status": status,
                "reserve_resources": reserve_resources,
                "last_task_id": str(last_task_id) if last_task_id else None,
                "deleted_at": deleted_at,
                "ip_address": ip_address,
                "updated_at": datetime.now(timezone.utc),
            },
        ).mappings().first()
        if not row:
            raise NotFoundError(f"instance {instance_id} not found")
        return _to_instance(row)


class PostgresInstanceReadRepository(InstanceReadRepository):
    def __init__(self, session: Session):
        self.session = session

    def get(self, instance_id: UUID, tenant_id: UUID | None = None) -> Instance | None:
        conditions: list[str] = ["id = :id"]
        params: dict[str, object] = {"id": str(instance_id)}
        if tenant_id is not None:
            conditions.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)
        row = self.session.execute(
            text(f"SELECT * FROM instances WHERE {' AND '.join(conditions)}"),
            params,
        ).mappings().first()
        return _to_instance(row) if row else None

    def list(
        self,
        limit: int,
        offset: int,
        status: str | None,
        name: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[Instance], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if name:
            conditions.append("name ILIKE :name")
            params["name"] = f"%{name}%"
        if tenant_id is not None:
            conditions.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self.session.execute(
            text(
                f"""
                SELECT * FROM instances
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()

        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM instances {where_clause}"),
            params,
        ).mappings().one()

        return ([_to_instance(row) for row in rows], int(count_row["total"]))


