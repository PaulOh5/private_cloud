from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.adapters.postgres_repositories import (
    PostgresTenantQuotaRepository,
    PostgresTenantRepository,
    PostgresTenantUsageReadRepository,
)
from app.api.dependencies import get_session, get_uow, require_roles
from app.api.schemas import (
    CreateTenantRequest,
    ListTenantsResponse,
    TenantQuotaResponse,
    TenantResponse,
    TenantUsageResponse,
    UpdateTenantQuotaRequest,
    UpdateTenantRequest,
)
from app.application.commands.tenant_commands import (
    CreateTenantCommand,
    CreateTenantHandler,
    DeleteTenantCommand,
    DeleteTenantHandler,
    UpdateTenantCommand,
    UpdateTenantHandler,
    UpdateTenantQuotaCommand,
    UpdateTenantQuotaHandler,
)
from app.application.queries.get_tenant import GetTenantHandler
from app.application.queries.get_tenant_usage import GetTenantUsageHandler
from app.application.queries.list_tenants import ListTenantsHandler, ListTenantsQuery
from app.application.services.audit_logger import AuditLogger
from app.domain.auth import User
from app.domain.errors import ConflictError, QuotaConflictError, TenantNotFoundError
from app.infra.uow import SqlAlchemyUnitOfWork


tenant_router = APIRouter(prefix="/tenants", tags=["tenants"])


def _to_quota_response(quota) -> TenantQuotaResponse:
    return TenantQuotaResponse(
        tenant_id=quota.tenant_id,
        max_instances=quota.max_instances,
        max_cpu=quota.max_cpu,
        max_memory_mib=quota.max_memory_mib,
        max_disk_gib=quota.max_disk_gib,
        updated_at=quota.updated_at,
    )


def _to_tenant_response(tenant, quota) -> TenantResponse:
    return TenantResponse(
        id=tenant.id,
        key=tenant.key,
        name=tenant.name,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        quota=_to_quota_response(quota) if quota else None,
    )


@tenant_router.post("", response_model=TenantResponse, status_code=201)
def create_tenant(
    body: CreateTenantRequest,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("admin")),
):
    handler = CreateTenantHandler(
        tenant_repository=PostgresTenantRepository(session),
        tenant_quota_repository=PostgresTenantQuotaRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        tenant, quota = handler.handle(
            CreateTenantCommand(
                key=body.key,
                name=body.name,
                is_active=body.is_active,
                max_instances=body.max_instances,
                max_cpu=body.max_cpu,
                max_memory_mib=body.max_memory_mib,
                max_disk_gib=body.max_disk_gib,
                actor=current_user,
            )
        )
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_tenant_response(tenant, quota)


@tenant_router.get("", response_model=ListTenantsResponse)
def list_tenants(
    session: Session = Depends(get_session),
    _uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    _current_user: User = Depends(require_roles("admin")),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    is_active: bool | None = Query(default=None),
):
    handler = ListTenantsHandler(
        tenant_repository=PostgresTenantRepository(session),
        tenant_quota_repository=PostgresTenantQuotaRepository(session),
    )
    result = handler.handle(
        ListTenantsQuery(
            limit=limit,
            offset=offset,
            is_active=is_active,
        )
    )
    responses = [_to_tenant_response(item.tenant, item.quota) for item in result.items]
    return ListTenantsResponse(items=responses, total=result.total, limit=limit, offset=offset)


@tenant_router.get("/{tenant_id}", response_model=TenantResponse)
def get_tenant(
    tenant_id: UUID,
    session: Session = Depends(get_session),
    _uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    _current_user: User = Depends(require_roles("admin")),
):
    handler = GetTenantHandler(
        tenant_repository=PostgresTenantRepository(session),
        tenant_quota_repository=PostgresTenantQuotaRepository(session),
    )
    try:
        detail = handler.handle(tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_tenant_response(detail.tenant, detail.quota)


@tenant_router.patch("/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: UUID,
    body: UpdateTenantRequest,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("admin")),
):
    handler = UpdateTenantHandler(
        tenant_repository=PostgresTenantRepository(session),
        tenant_quota_repository=PostgresTenantQuotaRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        updated, quota = handler.handle(
            UpdateTenantCommand(
                tenant_id=tenant_id,
                name=body.name,
                is_active=body.is_active,
                actor=current_user,
            )
        )
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_tenant_response(updated, quota)


@tenant_router.patch("/{tenant_id}/quota", response_model=TenantQuotaResponse)
def update_tenant_quota(
    tenant_id: UUID,
    body: UpdateTenantQuotaRequest,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("admin")),
):
    handler = UpdateTenantQuotaHandler(
        tenant_repository=PostgresTenantRepository(session),
        tenant_quota_repository=PostgresTenantQuotaRepository(session),
        tenant_usage_read_port=PostgresTenantUsageReadRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        updated = handler.handle(
            UpdateTenantQuotaCommand(
                tenant_id=tenant_id,
                max_instances=body.max_instances,
                max_cpu=body.max_cpu,
                max_memory_mib=body.max_memory_mib,
                max_disk_gib=body.max_disk_gib,
                actor=current_user,
            )
        )
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except QuotaConflictError:
        raise
    return _to_quota_response(updated)


@tenant_router.get("/{tenant_id}/usage", response_model=TenantUsageResponse)
def get_tenant_usage(
    tenant_id: UUID,
    session: Session = Depends(get_session),
    _uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    _current_user: User = Depends(require_roles("admin")),
):
    handler = GetTenantUsageHandler(tenant_usage_read_port=PostgresTenantUsageReadRepository(session))
    usage = handler.handle(tenant_id)
    return TenantUsageResponse(
        tenant_id=usage.tenant_id,
        used_instances=usage.used_instances,
        used_cpu=usage.used_cpu,
        used_memory_mib=usage.used_memory_mib,
        used_disk_gib=usage.used_disk_gib,
    )


@tenant_router.delete("/{tenant_id}", status_code=204)
def delete_tenant(
    tenant_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("admin")),
):
    handler = DeleteTenantHandler(
        tenant_repository=PostgresTenantRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        handler.handle(DeleteTenantCommand(tenant_id=tenant_id, actor=current_user))
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=204)
