from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AccessTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class CurrentUserResponse(BaseModel):
    id: UUID
    username: str
    role: str
    tenant_id: UUID | None
    is_active: bool


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=20)
