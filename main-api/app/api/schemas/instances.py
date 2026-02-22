from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateInstanceRequest(BaseModel):
    tenant_id: UUID | None = None
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
