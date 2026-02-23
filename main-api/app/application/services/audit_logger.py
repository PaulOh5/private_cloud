from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.postgres_repositories import PostgresAuditLogRepository
from app.domain.auth import User


@dataclass(frozen=True)
class AuditContext:
    request_id: UUID
    ip_address: str | None
    user_agent: str | None


class AuditLogger:
    def __init__(self, session: AsyncSession, request: Request | None):
        self._session = session
        self._request = request
        self._ctx = AuditContext(
            request_id=_parse_request_id(request),
            ip_address=_parse_ip_address(request),
            user_agent=request.headers.get("user-agent") if request else None,
        )

    async def write(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str | None,
        actor_user: User | None = None,
        actor_username: str | None = None,
        tenant_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> None:
        await PostgresAuditLogRepository(self._session).create(
            actor_user_id=actor_user.id if actor_user else None,
            actor_username=actor_username
            or (actor_user.username if actor_user else None),
            tenant_id=tenant_id
            if tenant_id is not None
            else (actor_user.tenant_id if actor_user else None),
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=self._ctx.request_id,
            ip_address=self._ctx.ip_address,
            user_agent=self._ctx.user_agent,
            metadata=metadata or {},
        )


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


async def write_audit_log(
    *,
    session: AsyncSession,
    request: Request | None,
    action: str,
    target_type: str,
    target_id: str | None,
    actor_user: User | None = None,
    actor_username: str | None = None,
    tenant_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    await AuditLogger(session, request).write(
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_user=actor_user,
        actor_username=actor_username,
        tenant_id=tenant_id,
        metadata=metadata,
    )
