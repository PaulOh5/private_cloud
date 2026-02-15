from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateInstanceRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    cpu: int = Field(gt=0)
    memory_mib: int = Field(gt=0)
    disk_gib: int = Field(gt=0)
    image_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")


class UpdateInstanceRequest(BaseModel):
    cpu: int = Field(gt=0)
    memory_mib: int = Field(gt=0)
    disk_gib: int = Field(gt=0)


class InstanceResponse(BaseModel):
    id: UUID
    name: str | None
    cpu: int
    memory_mib: int
    disk_gib: int
    status: str
    ip_address: str | None
    host_node: str
    created_at: datetime
    updated_at: datetime


class ListInstancesResponse(BaseModel):
    items: list[InstanceResponse]
    total: int
    limit: int
    offset: int


class VmImageResponse(BaseModel):
    id: str
    url: str
    format: str
    is_default: bool
    has_checksum: bool
    description: str | None = None


class ListVmImagesResponse(BaseModel):
    items: list[VmImageResponse]


class SyncVmImagesResponseItem(BaseModel):
    id: str
    path: str


class SyncVmImagesResponse(BaseModel):
    status: str
    default_image_id: str
    total_images: int
    synchronized_items: list[SyncVmImagesResponseItem]


class InstanceTaskAcceptedResponse(BaseModel):
    task_id: UUID
    instance_id: UUID
    status: str
    command: str
    accepted_at: datetime


class ConsoleTicketResponse(BaseModel):
    ticket: str
    expires_at: datetime
    websocket_path: str


class CancelTaskRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class TaskResponse(BaseModel):
    id: UUID
    instance_id: UUID
    command: str
    status: str
    request_id: UUID
    request_payload: dict
    result_payload: dict | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class ListTasksResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    code: str
    message: str


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
    is_active: bool


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class RoleResponse(BaseModel):
    name: str


class ListRolesResponse(BaseModel):
    items: list[RoleResponse]


class UserResponse(BaseModel):
    id: UUID
    username: str
    role: str
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
    is_active: bool = True


class UpdateUserRequest(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|operator|viewer)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class AuditLogResponse(BaseModel):
    id: UUID
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
