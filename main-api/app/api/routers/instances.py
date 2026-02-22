from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    build_vm_mutation_deps,
    build_vm_query_deps,
    ensure_instance_access,
    ensure_mutation_allowed_for_user_tenant,
    get_session,
    get_uow,
    require_roles,
    resolve_tenant_for_create,
    resolve_tenant_scope_for_list,
)
from app.api.routers.common import to_instance_response
from app.api.schemas import (
    ConsoleTicketResponse,
    CreateInstanceRequest,
    InstanceResponse,
    InstanceTaskAcceptedResponse,
    ListInstancesResponse,
    UpdateInstanceRequest,
)
from app.application.commands.instance_commands import (
    CreateInstanceCommand,
    CreateInstanceHandler,
    DeleteInstanceCommand,
    DeleteInstanceHandler,
    StartInstanceCommand,
    StartInstanceHandler,
    StopInstanceCommand,
    StopInstanceHandler,
    UpdateInstanceCommand,
    UpdateInstanceHandler,
)
from app.application.queries.get_instance import GetInstanceHandler
from app.application.services.audit_logger import write_audit_log
from app.application.queries.list_instances import ListInstancesHandler, ListInstancesQuery
from app.application.services.console_port import compute_console_vnc_port
from app.config import Settings
from app.domain.auth import User
from app.infra.uow import SqlAlchemyUnitOfWork

instance_router = APIRouter(prefix="/instances", tags=["instances"])
logger = logging.getLogger(__name__)


@instance_router.post("", response_model=InstanceTaskAcceptedResponse, status_code=202)
def create_instance(
    body: CreateInstanceRequest,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    deps = build_vm_mutation_deps(session, outbox_notify_channel=settings.outbox_notify_channel)
    ensure_mutation_allowed_for_user_tenant(session, current_user)
    tenant_id = resolve_tenant_for_create(current_user, body.tenant_id)
    uow.advisory_lock(4001)
    handler = CreateInstanceHandler(
        write_repository=deps.write_repository,
        task_repository=deps.task_repository,
        outbox_repository=deps.outbox_repository,
        outbox_max_attempts=settings.outbox_max_attempts,
        accounting=deps.accounting,
        quota_accounting=deps.quota_accounting,
    )
    accepted = handler.handle(
        CreateInstanceCommand(
            tenant_id=tenant_id,
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
        tenant_id=tenant_id,
        metadata={"task_id": str(accepted.task_id)},
    )
    uow.commit()
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
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    deps = build_vm_mutation_deps(session, outbox_notify_channel=settings.outbox_notify_channel)
    ensure_mutation_allowed_for_user_tenant(session, current_user)
    existing = deps.read_repository.get(instance_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")
    ensure_instance_access(current_user, existing.tenant_id)
    uow.advisory_lock(4001)
    handler = UpdateInstanceHandler(
        write_repository=deps.write_repository,
        task_repository=deps.task_repository,
        outbox_repository=deps.outbox_repository,
        outbox_max_attempts=settings.outbox_max_attempts,
        accounting=deps.accounting,
        quota_accounting=deps.quota_accounting,
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
        tenant_id=existing.tenant_id,
        metadata={"task_id": str(accepted.task_id)},
    )
    uow.commit()
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
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    deps = build_vm_mutation_deps(session, outbox_notify_channel=settings.outbox_notify_channel)
    ensure_mutation_allowed_for_user_tenant(session, current_user)
    existing = deps.read_repository.get(instance_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")
    ensure_instance_access(current_user, existing.tenant_id)
    uow.advisory_lock(4001)
    handler = DeleteInstanceHandler(
        write_repository=deps.write_repository,
        task_repository=deps.task_repository,
        outbox_repository=deps.outbox_repository,
        outbox_max_attempts=settings.outbox_max_attempts,
    )
    accepted = handler.handle(DeleteInstanceCommand(instance_id=instance_id))
    write_audit_log(
        session=session,
        request=request,
        action="instance.delete.requested",
        target_type="instance",
        target_id=str(instance_id),
        actor_user=current_user,
        tenant_id=existing.tenant_id,
        metadata={"task_id": str(accepted.task_id)},
    )
    uow.commit()
    return InstanceTaskAcceptedResponse(
        task_id=accepted.task_id,
        instance_id=accepted.instance_id,
        status=accepted.status,
        command=accepted.command,
        accepted_at=accepted.accepted_at,
    )


@instance_router.post("/{instance_id}/stop", response_model=InstanceTaskAcceptedResponse, status_code=202)
def stop_instance(
    instance_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    deps = build_vm_mutation_deps(session, outbox_notify_channel=settings.outbox_notify_channel)
    ensure_mutation_allowed_for_user_tenant(session, current_user)
    existing = deps.read_repository.get(instance_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")
    ensure_instance_access(current_user, existing.tenant_id)
    uow.advisory_lock(4001)
    handler = StopInstanceHandler(
        write_repository=deps.write_repository,
        task_repository=deps.task_repository,
        outbox_repository=deps.outbox_repository,
        outbox_max_attempts=settings.outbox_max_attempts,
    )
    accepted = handler.handle(StopInstanceCommand(instance_id=instance_id))
    write_audit_log(
        session=session,
        request=request,
        action="instance.stop.requested",
        target_type="instance",
        target_id=str(instance_id),
        actor_user=current_user,
        tenant_id=existing.tenant_id,
        metadata={"task_id": str(accepted.task_id)},
    )
    uow.commit()
    return InstanceTaskAcceptedResponse(
        task_id=accepted.task_id,
        instance_id=accepted.instance_id,
        status=accepted.status,
        command=accepted.command,
        accepted_at=accepted.accepted_at,
    )


@instance_router.post("/{instance_id}/start", response_model=InstanceTaskAcceptedResponse, status_code=202)
def start_instance(
    instance_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    settings: Settings = request.app.state.settings
    deps = build_vm_mutation_deps(session, outbox_notify_channel=settings.outbox_notify_channel)
    ensure_mutation_allowed_for_user_tenant(session, current_user)
    existing = deps.read_repository.get(instance_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")
    ensure_instance_access(current_user, existing.tenant_id)
    uow.advisory_lock(4001)
    handler = StartInstanceHandler(
        write_repository=deps.write_repository,
        task_repository=deps.task_repository,
        outbox_repository=deps.outbox_repository,
        outbox_max_attempts=settings.outbox_max_attempts,
        accounting=deps.accounting,
        quota_accounting=deps.quota_accounting,
    )
    accepted = handler.handle(StartInstanceCommand(instance_id=instance_id, host_node=settings.host_node))
    write_audit_log(
        session=session,
        request=request,
        action="instance.start.requested",
        target_type="instance",
        target_id=str(instance_id),
        actor_user=current_user,
        tenant_id=existing.tenant_id,
        metadata={"task_id": str(accepted.task_id)},
    )
    uow.commit()
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
    tenant_id: UUID | None = Query(default=None),
    current_user: User = Depends(require_roles("viewer", "operator", "admin")),
):
    deps = build_vm_query_deps(session)
    effective_tenant_id = resolve_tenant_scope_for_list(current_user, tenant_id)
    handler = ListInstancesHandler(read_repository=deps.read_repository)
    result = handler.handle(
        ListInstancesQuery(
            limit=limit,
            offset=offset,
            status=status,
            name=name,
            tenant_id=effective_tenant_id,
        )
    )
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
    current_user: User = Depends(require_roles("viewer", "operator", "admin")),
):
    deps = build_vm_query_deps(session)
    handler = GetInstanceHandler(read_repository=deps.read_repository)
    instance = handler.handle(instance_id)
    ensure_instance_access(current_user, instance.tenant_id)
    return to_instance_response(instance)


@instance_router.post("/{instance_id}/console-ticket", response_model=ConsoleTicketResponse)
def issue_console_ticket(
    instance_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("operator", "admin")),
):
    deps = build_vm_query_deps(session)
    handler = GetInstanceHandler(read_repository=deps.read_repository)
    instance = handler.handle(instance_id)
    ensure_instance_access(current_user, instance.tenant_id)
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
        tenant_id=instance.tenant_id,
        metadata={"expires_at": ticket.expires_at.isoformat()},
    )
    uow.commit()
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
