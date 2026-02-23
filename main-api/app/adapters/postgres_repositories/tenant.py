from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import Tenant, TenantQuota, TenantUsage
from app.ports import TenantQuotaRepository, TenantRepository, TenantUsageReadPort

from .common import to_tenant, to_tenant_quota, to_tenant_usage
from .orm.instance import InstanceModel
from .orm.resource import tenant_resource_usage_view
from .orm.tenant import TenantModel, TenantQuotaModel
from .orm.auth import UserModel


class PostgresTenantRepository(TenantRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, key: str, name: str, is_active: bool = True) -> Tenant:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(TenantModel)
            .values(
                id=uuid4(),
                key=key,
                name=name,
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[TenantModel.key])
            .returning(TenantModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise ConflictError(f"tenant key {key} already exists")
        return to_tenant(model)

    async def get(self, tenant_id: UUID) -> Tenant | None:
        model = await self.session.scalar(
            select(TenantModel).where(TenantModel.id == tenant_id)
        )
        return to_tenant(model) if model else None

    async def is_active(self, tenant_id: UUID) -> bool | None:
        value = await self.session.scalar(
            select(TenantModel.is_active).where(TenantModel.id == tenant_id)
        )
        if value is None:
            return None
        return bool(value)

    async def get_by_key(self, key: str) -> Tenant | None:
        model = await self.session.scalar(
            select(TenantModel).where(TenantModel.key == key)
        )
        return to_tenant(model) if model else None

    async def list(
        self, *, limit: int, offset: int, is_active: bool | None
    ) -> tuple[list[Tenant], int]:
        stmt = (
            select(TenantModel)
            .order_by(TenantModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count()).select_from(TenantModel)
        if is_active is not None:
            stmt = stmt.where(TenantModel.is_active == is_active)
            count_stmt = count_stmt.where(TenantModel.is_active == is_active)

        models = (await self.session.scalars(stmt)).all()
        total = int((await self.session.scalar(count_stmt)) or 0)
        return ([to_tenant(model) for model in models], total)

    async def update(
        self, tenant_id: UUID, *, name: str | None = None, is_active: bool | None = None
    ) -> Tenant:
        stmt = (
            update(TenantModel)
            .where(TenantModel.id == tenant_id)
            .values(
                name=func.coalesce(name, TenantModel.name),
                is_active=func.coalesce(is_active, TenantModel.is_active),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(TenantModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return to_tenant(model)

    async def delete(self, tenant_id: UUID) -> None:
        model = await self.session.scalar(
            select(TenantModel).where(TenantModel.id == tenant_id).with_for_update()
        )
        if not model:
            raise NotFoundError(f"tenant {tenant_id} not found")
        await self.session.delete(model)
        await self.session.flush()

    async def count_active_users(self, tenant_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(UserModel)
            .where(
                and_(UserModel.tenant_id == tenant_id, UserModel.is_active.is_(True))
            )
        )
        return int((await self.session.scalar(stmt)) or 0)

    async def count_active_instances(self, tenant_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(InstanceModel)
            .where(
                and_(
                    InstanceModel.tenant_id == tenant_id,
                    InstanceModel.status != "deleted",
                )
            )
        )
        return int((await self.session.scalar(stmt)) or 0)


class PostgresTenantQuotaRepository(TenantQuotaRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, tenant_id: UUID) -> TenantQuota | None:
        model = await self.session.scalar(
            select(TenantQuotaModel).where(TenantQuotaModel.tenant_id == tenant_id)
        )
        return to_tenant_quota(model) if model else None

    async def upsert(
        self,
        tenant_id: UUID,
        *,
        max_instances: int,
        max_cpu: int,
        max_memory_mib: int,
        max_disk_gib: int,
    ) -> TenantQuota:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(TenantQuotaModel)
            .values(
                tenant_id=tenant_id,
                max_instances=max_instances,
                max_cpu=max_cpu,
                max_memory_mib=max_memory_mib,
                max_disk_gib=max_disk_gib,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[TenantQuotaModel.tenant_id],
                set_={
                    "max_instances": max_instances,
                    "max_cpu": max_cpu,
                    "max_memory_mib": max_memory_mib,
                    "max_disk_gib": max_disk_gib,
                    "updated_at": now,
                },
            )
            .returning(TenantQuotaModel)
        )
        model = await self.session.scalar(stmt)
        assert model is not None
        return to_tenant_quota(model)


class PostgresTenantUsageReadRepository(TenantUsageReadPort):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_usage(self, tenant_id: UUID) -> TenantUsage:
        used_instances = func.coalesce(
            tenant_resource_usage_view.c.used_instances, 0
        ).label("used_instances")
        used_cpu = func.coalesce(tenant_resource_usage_view.c.used_cpu, 0).label(
            "used_cpu"
        )
        used_memory = func.coalesce(
            tenant_resource_usage_view.c.used_memory_mib, 0
        ).label("used_memory_mib")
        used_disk = func.coalesce(tenant_resource_usage_view.c.used_disk_gib, 0).label(
            "used_disk_gib"
        )

        stmt = (
            select(
                TenantModel.id.label("tenant_id"),
                used_instances,
                used_cpu,
                used_memory,
                used_disk,
            )
            .select_from(TenantModel)
            .outerjoin(
                tenant_resource_usage_view,
                tenant_resource_usage_view.c.tenant_id == TenantModel.id,
            )
            .where(TenantModel.id == tenant_id)
        )
        row = (await self.session.execute(stmt)).one_or_none()
        if not row:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return to_tenant_usage(row)
