from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Role = Literal["admin", "operator", "viewer"]


@dataclass(frozen=True)
class User:
    id: UUID
    username: str
    password_hash: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: UUID | None = None


@dataclass(frozen=True)
class RefreshToken:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
