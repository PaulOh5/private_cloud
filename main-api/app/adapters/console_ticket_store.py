from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import UUID


@dataclass
class ConsoleTicketRecord:
    ticket: str
    instance_id: UUID
    issued_by_user_id: UUID
    expires_at: datetime
    used: bool


class ConsoleTicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, ConsoleTicketRecord] = {}
        self._lock = Lock()

    def issue(
        self, *, instance_id: UUID, issued_by_user_id: UUID, ttl_seconds: int
    ) -> ConsoleTicketRecord:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=max(ttl_seconds, 1))
        record = ConsoleTicketRecord(
            ticket=secrets.token_urlsafe(32),
            instance_id=instance_id,
            issued_by_user_id=issued_by_user_id,
            expires_at=expires_at,
            used=False,
        )
        with self._lock:
            self._prune_locked(now)
            self._tickets[record.ticket] = record
        return record

    def consume(self, *, ticket: str, instance_id: UUID) -> ConsoleTicketRecord | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune_locked(now)
            record = self._tickets.get(ticket)
            if record is None:
                return None
            if record.instance_id != instance_id:
                return None
            if record.used or record.expires_at <= now:
                return None
            record.used = True
            return record

    def _prune_locked(self, now: datetime) -> None:
        stale_keys = [
            key
            for key, value in self._tickets.items()
            if value.used or value.expires_at <= now
        ]
        for key in stale_keys:
            self._tickets.pop(key, None)
