from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import NotFoundError
from app.domain.models import InstanceTask
from app.ports import TaskRepository

from .common import to_task
from .orm.instance import InstanceModel
from .orm.task import InstanceTaskModel


class PostgresTaskRepository(TaskRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def has_active_task(self, instance_id: UUID) -> bool:
        active_exists = select(
            exists().where(
                and_(
                    InstanceTaskModel.instance_id == instance_id,
                    InstanceTaskModel.status.in_(
                        ("queued", "running", "cancel_pending")
                    ),
                )
            )
        )
        return bool(await self.session.scalar(active_exists))

    async def create_task(self, task: InstanceTask) -> InstanceTask:
        model = InstanceTaskModel(
            id=task.id,
            instance_id=task.instance_id,
            command=task.command,
            status=task.status,
            request_id=task.request_id,
            request_payload=task.request_payload,
            result_payload=task.result_payload,
            error_code=task.error_code,
            error_message=task.error_message,
            retry_of_task_id=None,
            canceled_by=None,
            cancel_reason=None,
            attempt_count=task.attempt_count,
            max_attempts=task.max_attempts,
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            updated_at=task.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_task(model)

    async def get(self, task_id: UUID) -> InstanceTask | None:
        model = await self.session.scalar(
            select(InstanceTaskModel).where(InstanceTaskModel.id == task_id)
        )
        return to_task(model) if model else None

    async def get_tenant_id(self, task_id: UUID) -> UUID | None:
        stmt = (
            select(InstanceModel.tenant_id)
            .join(InstanceTaskModel, InstanceTaskModel.instance_id == InstanceModel.id)
            .where(InstanceTaskModel.id == task_id)
        )
        return await self.session.scalar(stmt)

    async def get_for_update(self, task_id: UUID) -> InstanceTask | None:
        model = await self.session.scalar(
            select(InstanceTaskModel)
            .where(InstanceTaskModel.id == task_id)
            .with_for_update()
        )
        return to_task(model) if model else None

    async def list(
        self,
        limit: int,
        offset: int,
        status: str | None,
        instance_id: UUID | None,
        command: str | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[InstanceTask], int]:
        conditions = []
        if status:
            conditions.append(InstanceTaskModel.status == status)
        if instance_id:
            conditions.append(InstanceTaskModel.instance_id == instance_id)
        if command:
            conditions.append(InstanceTaskModel.command == command)
        if tenant_id is not None:
            conditions.append(InstanceModel.tenant_id == tenant_id)

        where_clause = and_(*conditions) if conditions else None

        stmt = (
            select(InstanceTaskModel)
            .join(InstanceModel, InstanceModel.id == InstanceTaskModel.instance_id)
            .order_by(InstanceTaskModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = (
            select(func.count())
            .select_from(InstanceTaskModel)
            .join(InstanceModel, InstanceModel.id == InstanceTaskModel.instance_id)
        )
        if where_clause is not None:
            stmt = stmt.where(where_clause)
            count_stmt = count_stmt.where(where_clause)

        models = (await self.session.scalars(stmt)).all()
        total = int((await self.session.scalar(count_stmt)) or 0)
        return ([to_task(model) for model in models], total)

    async def mark_running(self, task_id: UUID, attempt_count: int) -> InstanceTask:
        now = datetime.now(timezone.utc)
        stmt = (
            update(InstanceTaskModel)
            .where(InstanceTaskModel.id == task_id)
            .values(
                status="running",
                attempt_count=attempt_count,
                started_at=func.coalesce(InstanceTaskModel.started_at, now),
                updated_at=now,
            )
            .returning(InstanceTaskModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"task {task_id} not found")
        return to_task(model)

    async def mark_cancel_pending(
        self,
        task_id: UUID,
        canceled_by: UUID | None,
        cancel_reason: str | None,
    ) -> InstanceTask:
        now = datetime.now(timezone.utc)
        stmt = (
            update(InstanceTaskModel)
            .where(InstanceTaskModel.id == task_id)
            .values(
                status="cancel_pending",
                canceled_by=func.coalesce(canceled_by, InstanceTaskModel.canceled_by),
                cancel_reason=func.coalesce(
                    cancel_reason, InstanceTaskModel.cancel_reason
                ),
                updated_at=now,
            )
            .returning(InstanceTaskModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"task {task_id} not found")
        return to_task(model)

    async def mark_canceled(
        self,
        task_id: UUID,
        attempt_count: int,
        canceled_by: UUID | None,
        cancel_reason: str | None,
        result_payload: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> InstanceTask:
        now = datetime.now(timezone.utc)
        stmt = (
            update(InstanceTaskModel)
            .where(InstanceTaskModel.id == task_id)
            .values(
                status="canceled",
                attempt_count=attempt_count,
                result_payload=result_payload,
                error_code=error_code,
                error_message=error_message,
                canceled_by=func.coalesce(canceled_by, InstanceTaskModel.canceled_by),
                cancel_reason=func.coalesce(
                    cancel_reason, InstanceTaskModel.cancel_reason
                ),
                finished_at=now,
                updated_at=now,
            )
            .returning(InstanceTaskModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"task {task_id} not found")
        return to_task(model)

    async def clone_for_retry(
        self,
        source_task: InstanceTask,
        new_task_id: UUID,
        new_request_id: UUID,
        created_at: datetime,
    ) -> InstanceTask:
        model = InstanceTaskModel(
            id=new_task_id,
            instance_id=source_task.instance_id,
            command=source_task.command,
            status="queued",
            request_id=new_request_id,
            request_payload=source_task.request_payload,
            result_payload=None,
            error_code=None,
            error_message=None,
            retry_of_task_id=source_task.id,
            canceled_by=None,
            cancel_reason=None,
            attempt_count=0,
            max_attempts=source_task.max_attempts,
            created_at=created_at,
            started_at=None,
            finished_at=None,
            updated_at=created_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_task(model)

    async def mark_terminal(
        self,
        task_id: UUID,
        status: str,
        attempt_count: int,
        result_payload: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> InstanceTask:
        now = datetime.now(timezone.utc)
        stmt = (
            update(InstanceTaskModel)
            .where(InstanceTaskModel.id == task_id)
            .values(
                status=status,
                attempt_count=attempt_count,
                result_payload=result_payload,
                error_code=error_code,
                error_message=error_message,
                finished_at=now,
                updated_at=now,
            )
            .returning(InstanceTaskModel)
        )
        model = await self.session.scalar(stmt)
        if not model:
            raise NotFoundError(f"task {task_id} not found")
        return to_task(model)
