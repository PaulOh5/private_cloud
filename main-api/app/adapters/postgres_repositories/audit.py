from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import AuditLog
from app.ports import AuditLogRepository

from .common import to_audit_log
from .orm.audit import AuditLogModel


class PostgresAuditLogRepository(AuditLogRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        tenant_id: UUID | None,
        actor_user_id: UUID | None,
        actor_username: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        request_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        metadata: dict,
    ) -> AuditLog:
        model = AuditLogModel(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_=metadata or {},
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(model)
        await self.session.flush()
        return to_audit_log(model)

    async def get(self, log_id: UUID) -> AuditLog | None:
        model = await self.session.scalar(
            select(AuditLogModel).where(AuditLogModel.id == log_id)
        )
        return to_audit_log(model) if model else None

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        actor_user_id: UUID | None,
        action: str | None,
        target_type: str | None,
        request_id: UUID | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[AuditLog], int]:
        conditions = []
        if actor_user_id:
            conditions.append(AuditLogModel.actor_user_id == actor_user_id)
        if action:
            conditions.append(AuditLogModel.action == action)
        if target_type:
            conditions.append(AuditLogModel.target_type == target_type)
        if request_id:
            conditions.append(AuditLogModel.request_id == request_id)
        if tenant_id is not None:
            conditions.append(AuditLogModel.tenant_id == tenant_id)

        where_clause = and_(*conditions) if conditions else None

        stmt = (
            select(AuditLogModel)
            .order_by(AuditLogModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count()).select_from(AuditLogModel)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
            count_stmt = count_stmt.where(where_clause)

        models = (await self.session.scalars(stmt)).all()
        total = int((await self.session.scalar(count_stmt)) or 0)
        return ([to_audit_log(model) for model in models], total)
