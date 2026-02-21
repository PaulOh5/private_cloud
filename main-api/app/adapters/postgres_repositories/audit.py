from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.models import AuditLog
from app.ports import AuditLogRepository

from .common import _to_audit_log


class PostgresAuditLogRepository(AuditLogRepository):
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        tenant_id: UUID | None,
        actor_user_id: UUID | None,
        actor_username: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        request_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        metadata: dict,
    ) -> AuditLog:
        row = self.session.execute(
            text(
                """
                INSERT INTO audit_logs (
                    id, tenant_id, actor_user_id, actor_username, action, target_type, target_id,
                    request_id, ip_address, user_agent, metadata, created_at
                )
                VALUES (
                    :id, :tenant_id, :actor_user_id, :actor_username, :action, :target_type, :target_id,
                    :request_id, :ip_address, :user_agent, CAST(:metadata AS JSONB), :created_at
                )
                RETURNING *
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id) if tenant_id else None,
                "actor_user_id": str(actor_user_id) if actor_user_id else None,
                "actor_username": actor_username,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "request_id": str(request_id) if request_id else None,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "metadata": json.dumps(metadata or {}),
                "created_at": datetime.now(timezone.utc),
            },
        ).mappings().one()
        return _to_audit_log(row)

    def get(self, log_id: UUID) -> AuditLog | None:
        row = self.session.execute(
            text("SELECT * FROM audit_logs WHERE id = :id"),
            {"id": str(log_id)},
        ).mappings().first()
        return _to_audit_log(row) if row else None

    def list(
        self,
        *,
        limit: int,
        offset: int,
        actor_user_id: UUID | None,
        action: str | None,
        target_type: str | None,
        request_id: UUID | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[AuditLog], int]:
        conditions: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if actor_user_id:
            conditions.append("actor_user_id = :actor_user_id")
            params["actor_user_id"] = str(actor_user_id)
        if action:
            conditions.append("action = :action")
            params["action"] = action
        if target_type:
            conditions.append("target_type = :target_type")
            params["target_type"] = target_type
        if request_id:
            conditions.append("request_id = :request_id")
            params["request_id"] = str(request_id)
        if tenant_id is not None:
            conditions.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self.session.execute(
            text(
                f"""
                SELECT *
                FROM audit_logs
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        count_row = self.session.execute(
            text(f"SELECT COUNT(*) AS total FROM audit_logs {where_clause}"),
            params,
        ).mappings().one()
        return ([_to_audit_log(row) for row in rows], int(count_row["total"]))


