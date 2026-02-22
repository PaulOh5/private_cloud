from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.models import AuditLog
from app.ports import AuditLogRepository


@dataclass(frozen=True)
class ListAuditLogsQuery:
    limit: int
    offset: int
    actor_user_id: UUID | None = None
    action: str | None = None
    target_type: str | None = None
    request_id: UUID | None = None
    tenant_id: UUID | None = None


@dataclass(frozen=True)
class ListAuditLogsResult:
    items: list[AuditLog]
    total: int


class ListAuditLogsHandler:
    def __init__(self, audit_log_repository: AuditLogRepository):
        self.audit_log_repository = audit_log_repository

    def handle(self, query: ListAuditLogsQuery) -> ListAuditLogsResult:
        items, total = self.audit_log_repository.list(
            limit=query.limit,
            offset=query.offset,
            actor_user_id=query.actor_user_id,
            action=query.action,
            target_type=query.target_type,
            request_id=query.request_id,
            tenant_id=query.tenant_id,
        )
        return ListAuditLogsResult(items=items, total=total)
