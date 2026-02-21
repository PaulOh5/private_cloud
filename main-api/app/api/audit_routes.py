from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.adapters.postgres_repositories import PostgresAuditLogRepository
from app.api.dependencies import get_session, require_roles
from app.api.schemas import AuditLogResponse, ListAuditLogsResponse
from app.domain.auth import User
from app.domain.errors import NotFoundError

audit_router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


def _to_response(log) -> AuditLogResponse:
    return AuditLogResponse(
        id=log.id,
        tenant_id=log.tenant_id,
        actor_user_id=log.actor_user_id,
        actor_username=log.actor_username,
        action=log.action,
        target_type=log.target_type,
        target_id=log.target_id,
        request_id=log.request_id,
        ip_address=log.ip_address,
        user_agent=log.user_agent,
        metadata=log.metadata,
        created_at=log.created_at,
    )


@audit_router.get("", response_model=ListAuditLogsResponse)
def list_audit_logs(
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_roles("admin")),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor_user_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    request_id: UUID | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
):
    repo = PostgresAuditLogRepository(session)
    items, total = repo.list(
        limit=limit,
        offset=offset,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        request_id=request_id,
        tenant_id=tenant_id,
    )
    return ListAuditLogsResponse(
        items=[_to_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@audit_router.get("/{log_id}", response_model=AuditLogResponse)
def get_audit_log(
    log_id: UUID,
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_roles("admin")),
):
    repo = PostgresAuditLogRepository(session)
    log = repo.get(log_id)
    if not log:
        raise NotFoundError(f"audit log {log_id} not found")
    return _to_response(log)
