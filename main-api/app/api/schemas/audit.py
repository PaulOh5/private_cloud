from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    actor_user_id: UUID | None
    actor_username: str | None
    action: str
    target_type: str
    target_id: str | None
    request_id: UUID | None
    ip_address: str | None
    user_agent: str | None
    metadata: dict
    created_at: datetime


class ListAuditLogsResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    limit: int
    offset: int
