from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RoleResponse(BaseModel):
    name: str


class ListRolesResponse(BaseModel):
    items: list[RoleResponse]


class UserResponse(BaseModel):
    id: UUID
    username: str
    role: str
    tenant_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ListUsersResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(pattern="^(admin|operator|viewer)$")
    tenant_id: UUID | None = None
    is_active: bool = True


class UpdateUserRequest(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|operator|viewer)$")
    tenant_id: UUID | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)
