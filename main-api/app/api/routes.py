from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.adapters.postgres import PostgresInstanceReadRepository, PostgresInstanceRepository, PostgresTaskRepository
from app.adapters.resource_accounting import HostResourceAccountingAdapter
from app.api.audit import write_audit_log
from app.api.dependencies import advisory_lock, get_session, require_roles
from app.api.schemas import (
    CancelTaskRequest,
    CreateInstanceRequest,
    InstanceResponse,
    InstanceTaskAcceptedResponse,
    ListInstancesResponse,
    ListTasksResponse,
    TaskResponse,
    UpdateInstanceRequest,
)
from app.application.commands.create_instance import CreateInstanceCommand, CreateInstanceHandler
from app.application.commands.cancel_task import CancelTaskCommand, CancelTaskHandler
from app.application.commands.delete_instance import DeleteInstanceCommand, DeleteInstanceHandler
from app.application.commands.retry_task import RetryTaskCommand, RetryTaskHandler
from app.application.commands.update_instance import UpdateInstanceCommand, UpdateInstanceHandler
from app.application.queries.get_instance import GetInstanceHandler
from app.application.queries.get_task import GetTaskHandler
from app.application.queries.list_instances import ListInstancesHandler, ListInstancesQuery
from app.application.queries.list_tasks import ListTasksHandler, ListTasksQuery
from app.config import Settings
from app.domain.auth import User
from app.domain.errors import DomainError

instance_router = APIRouter(prefix="/instances", tags=["instances"])
task_router = APIRouter(prefix="/tasks", tags=["tasks"])


def to_instance_response(instance) -> InstanceResponse:
    return InstanceResponse(
        id=instance.id,
        name=instance.name,
        cpu=instance.resource_spec.cpu,
        memory_mib=instance.resource_spec.memory_mib,
        disk_gib=instance.resource_spec.disk_gib,
        status=instance.status,
        ip_address=instance.ip_address,
        host_node=instance.host_node,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


def to_task_response(task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        instance_id=task.instance_id,
        command=task.command,
        status=task.status,
        request_id=task.request_id,
        request_payload=task.request_payload,
        result_payload=task.result_payload,
        error_code=task.error_code,
        error_message=task.error_message,
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        updated_at=task.updated_at,
    )


@instance_router.post("", response_model=InstanceTaskAcceptedResponse, status_code=202)
def create_instance(
    body: CreateInstanceRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    advisory_lock(session)
    handler = CreateInstanceHandler(
        write_repository=PostgresInstanceRepository(session),
        task_repository=PostgresTaskRepository(session),
        provisioning=request.app.state.vm_port,
        accounting=HostResourceAccountingAdapter(session),
    )
    accepted = handler.handle(
        CreateInstanceCommand(
            name=body.name,
            cpu=body.cpu,
            memory_mib=body.memory_mib,
            disk_gib=body.disk_gib,
            host_node=settings.host_node,
        )
    )
    write_audit_log(
        session=session,
        request=request,
        action="instance.create.requested",
        target_type="instance",
        target_id=str(accepted.instance_id),
        actor_user=current_user,
        metadata={"task_id": str(accepted.task_id)},
    )
    session.commit()
    return InstanceTaskAcceptedResponse(
        task_id=accepted.task_id,
        instance_id=accepted.instance_id,
        status=accepted.status,
        command=accepted.command,
        accepted_at=accepted.accepted_at,
    )


@instance_router.put("/{instance_id}", response_model=InstanceTaskAcceptedResponse, status_code=202)
def update_instance(
    instance_id: UUID,
    body: UpdateInstanceRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    advisory_lock(session)
    handler = UpdateInstanceHandler(
        write_repository=PostgresInstanceRepository(session),
        task_repository=PostgresTaskRepository(session),
        provisioning=request.app.state.vm_port,
        accounting=HostResourceAccountingAdapter(session),
    )
    accepted = handler.handle(
        UpdateInstanceCommand(
            instance_id=instance_id,
            cpu=body.cpu,
            memory_mib=body.memory_mib,
            disk_gib=body.disk_gib,
            host_node=settings.host_node,
        )
    )
    write_audit_log(
        session=session,
        request=request,
        action="instance.update.requested",
        target_type="instance",
        target_id=str(instance_id),
        actor_user=current_user,
        metadata={"task_id": str(accepted.task_id)},
    )
    session.commit()
    return InstanceTaskAcceptedResponse(
        task_id=accepted.task_id,
        instance_id=accepted.instance_id,
        status=accepted.status,
        command=accepted.command,
        accepted_at=accepted.accepted_at,
    )


@instance_router.delete("/{instance_id}", response_model=InstanceTaskAcceptedResponse, status_code=202)
def delete_instance(
    instance_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    advisory_lock(session)
    handler = DeleteInstanceHandler(
        write_repository=PostgresInstanceRepository(session),
        task_repository=PostgresTaskRepository(session),
        provisioning=request.app.state.vm_port,
    )
    accepted = handler.handle(DeleteInstanceCommand(instance_id=instance_id))
    write_audit_log(
        session=session,
        request=request,
        action="instance.delete.requested",
        target_type="instance",
        target_id=str(instance_id),
        actor_user=current_user,
        metadata={"task_id": str(accepted.task_id)},
    )
    session.commit()
    return InstanceTaskAcceptedResponse(
        task_id=accepted.task_id,
        instance_id=accepted.instance_id,
        status=accepted.status,
        command=accepted.command,
        accepted_at=accepted.accepted_at,
    )


@instance_router.get("", response_model=ListInstancesResponse)
def list_instances(
    session: Session = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    name: str | None = Query(default=None),
    _=Depends(require_roles("viewer", "operator", "admin")),
):
    handler = ListInstancesHandler(read_repository=PostgresInstanceReadRepository(session))
    result = handler.handle(ListInstancesQuery(limit=limit, offset=offset, status=status, name=name))
    return ListInstancesResponse(
        items=[to_instance_response(instance) for instance in result.items],
        total=result.total,
        limit=limit,
        offset=offset,
    )


@instance_router.get("/{instance_id}", response_model=InstanceResponse)
def get_instance(
    instance_id: UUID,
    session: Session = Depends(get_session),
    _=Depends(require_roles("viewer", "operator", "admin")),
):
    handler = GetInstanceHandler(read_repository=PostgresInstanceReadRepository(session))
    return to_instance_response(handler.handle(instance_id))


@task_router.get("", response_model=ListTasksResponse)
def list_tasks(
    session: Session = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    instance_id: UUID | None = Query(default=None),
    command: str | None = Query(default=None),
    _=Depends(require_roles("viewer", "operator", "admin")),
):
    handler = ListTasksHandler(task_repository=PostgresTaskRepository(session))
    result = handler.handle(
        ListTasksQuery(limit=limit, offset=offset, status=status, instance_id=instance_id, command=command)
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
    _=Depends(require_roles("viewer", "operator", "admin")),
):
    handler = GetTaskHandler(task_repository=PostgresTaskRepository(session))
    return to_task_response(handler.handle(task_id))


@task_router.post("/{task_id}/retry", response_model=InstanceTaskAcceptedResponse, status_code=202)
def retry_task(
    task_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    advisory_lock(session)
    handler = RetryTaskHandler(
        write_repository=PostgresInstanceRepository(session),
        task_repository=PostgresTaskRepository(session),
        provisioning=request.app.state.vm_port,
        accounting=HostResourceAccountingAdapter(session),
    )
    accepted = handler.handle(RetryTaskCommand(task_id=task_id))
    write_audit_log(
        session=session,
        request=request,
        action="task.retry.requested",
        target_type="task",
        target_id=str(task_id),
        actor_user=current_user,
        metadata={
            "new_task_id": str(accepted.task_id),
            "instance_id": str(accepted.instance_id),
            "command": accepted.command,
        },
    )
    session.commit()
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
    current_user: User = Depends(require_roles("operator", "admin")),
):
    advisory_lock(session)
    handler = CancelTaskHandler(
        write_repository=PostgresInstanceRepository(session),
        task_repository=PostgresTaskRepository(session),
        provisioning=request.app.state.vm_port,
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
            metadata={"reason": body.reason if body else None, "error_code": exc.code, "error_message": str(exc)},
        )
        session.commit()
        raise

    write_audit_log(
        session=session,
        request=request,
        action="task.cancel.requested",
        target_type="task",
        target_id=str(task_id),
        actor_user=current_user,
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
            metadata={"reason": body.reason if body else None},
        )
    session.commit()
    return InstanceTaskAcceptedResponse(
        task_id=accepted.task_id,
        instance_id=accepted.instance_id,
        status=accepted.status,
        command=accepted.command,
        accepted_at=accepted.accepted_at,
    )
