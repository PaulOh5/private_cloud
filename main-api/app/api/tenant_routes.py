from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.adapters.postgres_repositories import (
    PostgresTenantQuotaRepository,
    PostgresTenantRepository,
    PostgresTenantUsageReadRepository,
)
from app.api.audit import write_audit_log
from app.api.dependencies import get_session, require_roles
from app.api.schemas import (
    CreateTenantRequest,
    ListTenantsResponse,
    TenantQuotaResponse,
    TenantResponse,
    TenantUsageResponse,
    UpdateTenantQuotaRequest,
    UpdateTenantRequest,
)
from app.domain.auth import User
from app.domain.errors import ConflictError, NotFoundError, QuotaConflictError

DEFAULT_TENANT_KEY = "default"


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
    current_user: User = Depends(require_roles("admin")),
):
    tenant_repo = PostgresTenantRepository(session)
    quota_repo = PostgresTenantQuotaRepository(session)

    try:
        tenant = tenant_repo.create(key=body.key, name=body.name, is_active=body.is_active)
    except ConflictError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tenant key already exists")

    quota = quota_repo.upsert(
        tenant.id,
        max_instances=body.max_instances,
        max_cpu=body.max_cpu,
        max_memory_mib=body.max_memory_mib,
        max_disk_gib=body.max_disk_gib,
    )

    write_audit_log(
        session=session,
        request=request,
        action="tenant.create",
        target_type="tenant",
        target_id=str(tenant.id),
        actor_user=current_user,
        tenant_id=tenant.id,
        metadata={
            "key": tenant.key,
            "max_instances": quota.max_instances,
            "max_cpu": quota.max_cpu,
            "max_memory_mib": quota.max_memory_mib,
            "max_disk_gib": quota.max_disk_gib,
        },
    )
    session.commit()
    return _to_tenant_response(tenant, quota)


@tenant_router.get("", response_model=ListTenantsResponse)
def list_tenants(
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_roles("admin")),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    is_active: bool | None = Query(default=None),
):
    tenant_repo = PostgresTenantRepository(session)
    quota_repo = PostgresTenantQuotaRepository(session)
    items, total = tenant_repo.list(limit=limit, offset=offset, is_active=is_active)

    responses = []
    for tenant in items:
        responses.append(_to_tenant_response(tenant, quota_repo.get(tenant.id)))

    return ListTenantsResponse(items=responses, total=total, limit=limit, offset=offset)


@tenant_router.get("/{tenant_id}", response_model=TenantResponse)
def get_tenant(
    tenant_id: UUID,
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_roles("admin")),
):
    tenant_repo = PostgresTenantRepository(session)
    quota_repo = PostgresTenantQuotaRepository(session)
    tenant = tenant_repo.get(tenant_id)
    if not tenant:
        raise NotFoundError(f"tenant {tenant_id} not found")
    return _to_tenant_response(tenant, quota_repo.get(tenant_id))


@tenant_router.patch("/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: UUID,
    body: UpdateTenantRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("admin")),
):
    tenant_repo = PostgresTenantRepository(session)
    quota_repo = PostgresTenantQuotaRepository(session)

    tenant = tenant_repo.get(tenant_id)
    if not tenant:
        raise NotFoundError(f"tenant {tenant_id} not found")
    if tenant.key == DEFAULT_TENANT_KEY and body.is_active is False:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="default tenant cannot be deactivated")

    updated = tenant_repo.update(tenant_id, name=body.name, is_active=body.is_active)
    write_audit_log(
        session=session,
        request=request,
        action="tenant.update",
        target_type="tenant",
        target_id=str(updated.id),
        actor_user=current_user,
        tenant_id=updated.id,
        metadata={"name": updated.name, "is_active": updated.is_active},
    )
    session.commit()
    return _to_tenant_response(updated, quota_repo.get(updated.id))


@tenant_router.patch("/{tenant_id}/quota", response_model=TenantQuotaResponse)
def update_tenant_quota(
    tenant_id: UUID,
    body: UpdateTenantQuotaRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("admin")),
):
    tenant_repo = PostgresTenantRepository(session)
    quota_repo = PostgresTenantQuotaRepository(session)
    usage_repo = PostgresTenantUsageReadRepository(session)

    tenant = tenant_repo.get(tenant_id)
    if not tenant:
        raise NotFoundError(f"tenant {tenant_id} not found")

    usage = usage_repo.get_usage(tenant_id)
    if body.max_instances < usage.used_instances:
        raise QuotaConflictError("max_instances cannot be lower than current usage")
    if body.max_cpu < usage.used_cpu:
        raise QuotaConflictError("max_cpu cannot be lower than current usage")
    if body.max_memory_mib < usage.used_memory_mib:
        raise QuotaConflictError("max_memory_mib cannot be lower than current usage")
    if body.max_disk_gib < usage.used_disk_gib:
        raise QuotaConflictError("max_disk_gib cannot be lower than current usage")

    updated = quota_repo.upsert(
        tenant_id,
        max_instances=body.max_instances,
        max_cpu=body.max_cpu,
        max_memory_mib=body.max_memory_mib,
        max_disk_gib=body.max_disk_gib,
    )

    write_audit_log(
        session=session,
        request=request,
        action="tenant.quota.update",
        target_type="tenant",
        target_id=str(tenant_id),
        actor_user=current_user,
        tenant_id=tenant_id,
        metadata={
            "max_instances": updated.max_instances,
            "max_cpu": updated.max_cpu,
            "max_memory_mib": updated.max_memory_mib,
            "max_disk_gib": updated.max_disk_gib,
        },
    )
    session.commit()
    return _to_quota_response(updated)


@tenant_router.get("/{tenant_id}/usage", response_model=TenantUsageResponse)
def get_tenant_usage(
    tenant_id: UUID,
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_roles("admin")),
):
    usage = PostgresTenantUsageReadRepository(session).get_usage(tenant_id)
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
    current_user: User = Depends(require_roles("admin")),
):
    tenant_repo = PostgresTenantRepository(session)
    tenant = tenant_repo.get(tenant_id)
    if not tenant:
        raise NotFoundError(f"tenant {tenant_id} not found")
    if tenant.key == DEFAULT_TENANT_KEY:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="default tenant cannot be deleted")

    if tenant_repo.count_active_users(tenant_id) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tenant has active users")
    if tenant_repo.count_active_instances(tenant_id) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tenant has active instances")

    tenant_repo.delete(tenant_id)
    write_audit_log(
        session=session,
        request=request,
        action="tenant.delete",
        target_type="tenant",
        target_id=str(tenant_id),
        actor_user=current_user,
        tenant_id=tenant_id,
    )
    session.commit()
    return Response(status_code=204)
