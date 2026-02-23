from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import NotFoundError
from app.domain.models import Instance, ResourceSpec
from app.ports import InstanceReadRepository, InstanceRepository

from .common import to_instance
from .orm.instance import InstanceModel


class PostgresInstanceRepository(InstanceRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_for_update(self, instance_id: UUID) -> Instance | None:
        model = await self.session.scalar(
            select(InstanceModel)
            .where(InstanceModel.id == instance_id)
            .with_for_update()
        )
        return to_instance(model) if model else None

    async def create(self, instance: Instance) -> Instance:
        model = InstanceModel(
            id=instance.id,
            tenant_id=instance.tenant_id,
            name=instance.name,
            cpu=instance.resource_spec.cpu,
            memory_mib=instance.resource_spec.memory_mib,
            disk_gib=instance.resource_spec.disk_gib,
            status=instance.status,
            ip_address=instance.ip_address,
            host_node=instance.host_node,
            reserve_resources=instance.reserve_resources,
            last_task_id=instance.last_task_id,
            deleted_at=instance.deleted_at,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_instance(model)

    async def update_spec(
        self,
        instance_id: UUID,
        spec: ResourceSpec,
        status: str,
        ip_address: str | None,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
    ) -> Instance:
        stmt = (
            update(InstanceModel)
            .where(InstanceModel.id == instance_id)
            .values(
                cpu=spec.cpu,
                memory_mib=spec.memory_mib,
                disk_gib=spec.disk_gib,
                status=status,
                ip_address=ip_address,
                reserve_resources=reserve_resources,
                last_task_id=last_task_id,
                deleted_at=deleted_at,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(InstanceModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"instance {instance_id} not found")
        return to_instance(model)

    async def update_state(
        self,
        instance_id: UUID,
        status: str,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
        ip_address: str | None,
    ) -> Instance:
        stmt = (
            update(InstanceModel)
            .where(InstanceModel.id == instance_id)
            .values(
                status=status,
                reserve_resources=reserve_resources,
                last_task_id=last_task_id,
                deleted_at=deleted_at,
                ip_address=ip_address,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(InstanceModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"instance {instance_id} not found")
        return to_instance(model)


class PostgresInstanceReadRepository(InstanceReadRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self, instance_id: UUID, tenant_id: UUID | None = None
    ) -> Instance | None:
        conditions = [InstanceModel.id == instance_id]
        if tenant_id is not None:
            conditions.append(InstanceModel.tenant_id == tenant_id)
        model = await self.session.scalar(
            select(InstanceModel).where(and_(*conditions))
        )
        return to_instance(model) if model else None

    async def list(
        self,
        limit: int,
        offset: int,
        status: str | None,
        name: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[Instance], int]:
        conditions = []
        if status:
            conditions.append(InstanceModel.status == status)
        if name:
            conditions.append(InstanceModel.name.ilike(f"%{name}%"))
        if tenant_id is not None:
            conditions.append(InstanceModel.tenant_id == tenant_id)

        where_clause = and_(*conditions) if conditions else None

        stmt = (
            select(InstanceModel)
            .order_by(InstanceModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count()).select_from(InstanceModel)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
            count_stmt = count_stmt.where(where_clause)

        models = (await self.session.scalars(stmt)).all()
        total = int((await self.session.scalar(count_stmt)) or 0)
        return ([to_instance(model) for model in models], total)
