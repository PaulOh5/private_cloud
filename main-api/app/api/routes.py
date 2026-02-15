import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.adapters.postgres import PostgresInstanceReadRepository, PostgresInstanceRepository, PostgresTaskRepository
from app.adapters.rabbitmq_image_sync_rpc import VmImageSyncRpcError
from app.adapters.resource_accounting import HostResourceAccountingAdapter
from app.api.audit import write_audit_log
from app.api.dependencies import advisory_lock, get_session, require_roles
from app.api.schemas import (
    CancelTaskRequest,
    ConsoleTicketResponse,
    CreateInstanceRequest,
    InstanceResponse,
    InstanceTaskAcceptedResponse,
    SyncVmImagesResponse,
    ListVmImagesResponse,
    ListInstancesResponse,
    ListTasksResponse,
    TaskResponse,
    UpdateInstanceRequest,
    VmImageResponse,
)
from app.application.commands.create_instance import CreateInstanceCommand, CreateInstanceHandler
from app.application.commands.cancel_task import CancelTaskCommand, CancelTaskHandler
from app.application.commands.delete_instance import DeleteInstanceCommand, DeleteInstanceHandler
from app.application.commands.retry_task import RetryTaskCommand, RetryTaskHandler
from app.application.commands.update_instance import UpdateInstanceCommand, UpdateInstanceHandler
from app.application.services.console_port import compute_console_vnc_port
from app.application.queries.get_instance import GetInstanceHandler
from app.application.queries.get_task import GetTaskHandler
from app.application.queries.list_instances import ListInstancesHandler, ListInstancesQuery
from app.application.queries.list_tasks import ListTasksHandler, ListTasksQuery
from app.config import Settings
from app.domain.auth import User
from app.domain.errors import DomainError

instance_router = APIRouter(prefix="/instances", tags=["instances"])
task_router = APIRouter(prefix="/tasks", tags=["tasks"])
image_router = APIRouter(prefix="/images", tags=["images"])
legacy_image_router = APIRouter(prefix="/image", tags=["images"])
logger = logging.getLogger(__name__)


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


@image_router.get("", response_model=ListVmImagesResponse)
def list_images(
    request: Request,
    _=Depends(require_roles("viewer", "operator", "admin")),
):
    catalog = request.app.state.vm_image_catalog
    return ListVmImagesResponse(
        items=[
            VmImageResponse(
                id=entry.id,
                url=entry.url,
                format=entry.image_format,
                is_default=entry.id == catalog.default_id,
                has_checksum=bool(entry.sha256),
                description=entry.description,
            )
            for entry in catalog.entries
        ]
    )


def _sync_images_impl(request: Request) -> SyncVmImagesResponse:
    try:
        result = request.app.state.vm_image_sync_port.sync_images()
    except VmImageSyncRpcError as exc:
        status_code = 502
        if exc.code == "VALIDATION_ERROR":
            status_code = 400
        elif exc.code == "TIMEOUT":
            status_code = 504
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc

    return SyncVmImagesResponse.model_validate(result)


@image_router.post("/sync", response_model=SyncVmImagesResponse)
def sync_images(
    request: Request,
    _=Depends(require_roles("admin")),
):
    return _sync_images_impl(request)


@legacy_image_router.post("/sync", response_model=SyncVmImagesResponse, include_in_schema=False)
def sync_images_legacy_alias(
    request: Request,
    _=Depends(require_roles("admin")),
):
    return _sync_images_impl(request)


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
            image_id=body.image_id,
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


@instance_router.post("/{instance_id}/console-ticket", response_model=ConsoleTicketResponse)
def issue_console_ticket(
    instance_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    handler = GetInstanceHandler(read_repository=PostgresInstanceReadRepository(session))
    instance = handler.handle(instance_id)
    if instance.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="console is available only when instance status is running",
        )

    settings: Settings = request.app.state.settings
    ticket_store = request.app.state.console_ticket_store
    ticket = ticket_store.issue(
        instance_id=instance_id,
        issued_by_user_id=current_user.id,
        ttl_seconds=settings.console_ticket_ttl_seconds,
    )
    write_audit_log(
        session=session,
        request=request,
        action="instance.console.ticket_issued",
        target_type="instance",
        target_id=str(instance_id),
        actor_user=current_user,
        metadata={"expires_at": ticket.expires_at.isoformat()},
    )
    session.commit()
    return ConsoleTicketResponse(
        ticket=ticket.ticket,
        expires_at=ticket.expires_at,
        websocket_path=f"/instances/{instance_id}/console/ws?ticket={ticket.ticket}",
    )


@instance_router.websocket("/{instance_id}/console/ws")
async def proxy_instance_console(
    websocket: WebSocket,
    instance_id: UUID,
    ticket: str = Query(..., min_length=8),
):
    ticket_store = websocket.app.state.console_ticket_store
    ticket_record = ticket_store.consume(ticket=ticket, instance_id=instance_id)
    if ticket_record is None:
        await websocket.close(code=1008, reason="invalid or expired ticket")
        return

    settings: Settings = websocket.app.state.settings
    vnc_port = compute_console_vnc_port(
        str(instance_id),
        base=settings.console_vnc_port_base,
        span=settings.console_vnc_port_span,
    )
    try:
        reader, writer = await asyncio.open_connection(settings.console_proxy_host, vnc_port)
    except Exception:
        await websocket.close(code=1011, reason="console backend unavailable")
        return

    requested_subprotocols = {
        item.strip().lower()
        for item in (websocket.headers.get("sec-websocket-protocol") or "").split(",")
        if item.strip()
    }
    if "binary" in requested_subprotocols:
        await websocket.accept(subprotocol="binary")
    else:
        await websocket.accept()

    async def client_to_vnc() -> None:
        sent_bytes = 0
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                logger.info(
                    "console ws client disconnect: instance_id=%s code=%s sent_bytes=%s",
                    instance_id,
                    message.get("code"),
                    sent_bytes,
                )
                return
            chunk = message.get("bytes")
            if chunk is None:
                text = message.get("text")
                if text is None:
                    continue
                chunk = text.encode("utf-8")
            writer.write(chunk)
            await writer.drain()
            sent_bytes += len(chunk)

    async def vnc_to_client() -> None:
        recv_bytes = 0
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                logger.info(
                    "console vnc eof: instance_id=%s recv_bytes=%s",
                    instance_id,
                    recv_bytes,
                )
                return
            await websocket.send_bytes(chunk)
            recv_bytes += len(chunk)

    tasks = [asyncio.create_task(client_to_vnc()), asyncio.create_task(vnc_to_client())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc is not None:
                logger.warning("console proxy task exception: instance_id=%s err=%r", instance_id, exc)
    except WebSocketDisconnect as exc:
        logger.info("console ws top-level disconnect: instance_id=%s code=%s", instance_id, exc.code)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception as exc:  # pragma: no cover
            logger.warning("console writer close error: instance_id=%s err=%r", instance_id, exc)
        try:
            await websocket.close()
        except RuntimeError:
            pass


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
