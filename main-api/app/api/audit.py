from __future__ import annotations

import ipaddress
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.adapters.postgres_repositories import PostgresAuditLogRepository
from app.domain.auth import User


def _parse_request_id(request: Request | None) -> UUID:
    if request is None:
        return uuid4()
    raw = request.headers.get("x-request-id")
    if not raw:
        return uuid4()
    try:
        return UUID(raw)
    except ValueError:
        return uuid4()


def _parse_ip_address(request: Request | None) -> str | None:
    raw = request.client.host if request and request.client else None
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def write_audit_log(
    *,
    session: Session,
    request: Request | None,
    action: str,
    target_type: str,
    target_id: str | None,
    actor_user: User | None = None,
    actor_username: str | None = None,
    tenant_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    ip_address = _parse_ip_address(request)
    user_agent = request.headers.get("user-agent") if request else None
    PostgresAuditLogRepository(session).create(
        actor_user_id=actor_user.id if actor_user else None,
        actor_username=actor_username or (actor_user.username if actor_user else None),
        tenant_id=tenant_id if tenant_id is not None else (actor_user.tenant_id if actor_user else None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        request_id=_parse_request_id(request),
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata or {},
    )
