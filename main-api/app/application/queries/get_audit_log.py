from __future__ import annotations
from uuid import UUID
from app.domain.errors import AuditLogNotFoundError
from app.domain.models import AuditLog
from app.ports import AuditLogRepository


class GetAuditLogHandler:
    def __init__(self, audit_log_repository: AuditLogRepository):
        self.audit_log_repository = audit_log_repository

    async def handle(self, log_id: UUID) -> AuditLog:
        log = await self.audit_log_repository.get(log_id)
        if not log:
            raise AuditLogNotFoundError(f"audit log {log_id} not found")
        return log
