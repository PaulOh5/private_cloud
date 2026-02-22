from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    build_vm_mutation_deps,
    build_vm_query_deps,
    ensure_mutation_allowed_for_user_tenant,
    ensure_task_access,
    get_session,
    get_uow,
    require_roles,
    resolve_tenant_scope_for_list,
)
from app.api.routers.common import get_task_tenant_id, to_task_response
from app.api.schemas import CancelTaskRequest, InstanceTaskAcceptedResponse, ListTasksResponse, TaskResponse
from app.application.commands.task_commands import (
    CancelTaskCommand,
    CancelTaskHandler,
    RetryTaskCommand,
    RetryTaskHandler,
)
from app.application.queries.get_task import GetTaskHandler
from app.application.queries.list_tasks import ListTasksHandler, ListTasksQuery
from app.application.services.audit_logger import write_audit_log
from app.config import Settings
from app.domain.auth import User
from app.domain.errors import DomainError
from app.infra.uow import SqlAlchemyUnitOfWork

task_router = APIRouter(prefix="/tasks", tags=["tasks"])


@task_router.get("", response_model=ListTasksResponse)
def list_tasks(
    session: Session = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    instance_id: UUID | None = Query(default=None),
    command: str | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
    current_user: User = Depends(require_roles("viewer", "operator", "admin")),
):
    deps = build_vm_query_deps(session)
    effective_tenant_id = resolve_tenant_scope_for_list(current_user, tenant_id)
    handler = ListTasksHandler(task_repository=deps.task_repository)
    result = handler.handle(
        ListTasksQuery(
            limit=limit,
            offset=offset,
            status=status,
            instance_id=instance_id,
            command=command,
            tenant_id=effective_tenant_id,
        )
    )
    return ListTasksResponse(
        items=[to_task_response(task) for task in result.items],
        total=result.total,
        limit=limit,
        offset=offset,
    )


@task_router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("viewer", "operator", "admin")),
):
    deps = build_vm_query_deps(session)
    task_tenant_id = get_task_tenant_id(session, task_id)
    if task_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    ensure_task_access(current_user, task_tenant_id)
    handler = GetTaskHandler(task_repository=deps.task_repository)
    return to_task_response(handler.handle(task_id))


@task_router.post("/{task_id}/retry", response_model=InstanceTaskAcceptedResponse, status_code=202)
def retry_task(
    task_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    deps = build_vm_mutation_deps(session, outbox_notify_channel=settings.outbox_notify_channel)
    ensure_mutation_allowed_for_user_tenant(session, current_user)
    task_tenant_id = get_task_tenant_id(session, task_id)
    if task_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    ensure_task_access(current_user, task_tenant_id)
    uow.advisory_lock(4001)
    handler = RetryTaskHandler(
        write_repository=deps.write_repository,
        task_repository=deps.task_repository,
        outbox_repository=deps.outbox_repository,
        outbox_max_attempts=settings.outbox_max_attempts,
        accounting=deps.accounting,
        quota_accounting=deps.quota_accounting,
    )
    accepted = handler.handle(RetryTaskCommand(task_id=task_id))
    write_audit_log(
        session=session,
        request=request,
        action="task.retry.requested",
        target_type="task",
        target_id=str(task_id),
        actor_user=current_user,
        tenant_id=task_tenant_id,
        metadata={
            "new_task_id": str(accepted.task_id),
            "instance_id": str(accepted.instance_id),
            "command": accepted.command,
        },
    )
    uow.commit()
    return InstanceTaskAcceptedResponse(
        task_id=accepted.task_id,
        instance_id=accepted.instance_id,
        status=accepted.status,
        command=accepted.command,
        accepted_at=accepted.accepted_at,
    )


@task_router.post("/{task_id}/cancel", response_model=InstanceTaskAcceptedResponse, status_code=202)
def cancel_task(
    task_id: UUID,
    request: Request,
    body: CancelTaskRequest | None = None,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    deps = build_vm_mutation_deps(session, outbox_notify_channel=settings.outbox_notify_channel)
    ensure_mutation_allowed_for_user_tenant(session, current_user)
    task_tenant_id = get_task_tenant_id(session, task_id)
    if task_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    ensure_task_access(current_user, task_tenant_id)
    uow.advisory_lock(4001)
    handler = CancelTaskHandler(
        write_repository=deps.write_repository,
        task_repository=deps.task_repository,
        outbox_repository=deps.outbox_repository,
        outbox_max_attempts=settings.outbox_max_attempts,
    )
    try:
        accepted = handler.handle(
            CancelTaskCommand(
                task_id=task_id,
                actor_user_id=current_user.id,
                reason=body.reason if body else None,
            )
        )
    except DomainError as exc:
        write_audit_log(
            session=session,
            request=request,
            action="task.cancel.failed",
            target_type="task",
            target_id=str(task_id),
            actor_user=current_user,
            tenant_id=task_tenant_id,
            metadata={"reason": body.reason if body else None, "error_code": exc.code, "error_message": str(exc)},
        )
        uow.commit()
        raise

    write_audit_log(
        session=session,
        request=request,
        action="task.cancel.requested",
        target_type="task",
        target_id=str(task_id),
        actor_user=current_user,
        tenant_id=task_tenant_id,
        metadata={
            "reason": body.reason if body else None,
            "result_status": accepted.status,
            "instance_id": str(accepted.instance_id),
        },
    )
    if accepted.status == "canceled":
        write_audit_log(
            session=session,
            request=request,
            action="task.cancel.completed",
            target_type="task",
            target_id=str(task_id),
            actor_user=current_user,
            tenant_id=task_tenant_id,
            metadata={"reason": body.reason if body else None},
        )
    uow.commit()
    return InstanceTaskAcceptedResponse(
        task_id=accepted.task_id,
        instance_id=accepted.instance_id,
        status=accepted.status,
        command=accepted.command,
        accepted_at=accepted.accepted_at,
    )
