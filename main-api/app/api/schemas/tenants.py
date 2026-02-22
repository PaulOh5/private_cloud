from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TenantQuotaResponse(BaseModel):
    tenant_id: UUID
    max_instances: int
    max_cpu: int
    max_memory_mib: int
    max_disk_gib: int
    updated_at: datetime


class TenantResponse(BaseModel):
    id: UUID
    key: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    quota: TenantQuotaResponse | None = None


class ListTenantsResponse(BaseModel):
    items: list[TenantResponse]
    total: int
    limit: int
    offset: int


class CreateTenantRequest(BaseModel):
    key: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    name: str = Field(min_length=1, max_length=128)
    is_active: bool = True
    max_instances: int = Field(gt=0)
    max_cpu: int = Field(gt=0)
    max_memory_mib: int = Field(gt=0)
    max_disk_gib: int = Field(gt=0)


class UpdateTenantRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None


class UpdateTenantQuotaRequest(BaseModel):
    max_instances: int = Field(gt=0)
    max_cpu: int = Field(gt=0)
    max_memory_mib: int = Field(gt=0)
    max_disk_gib: int = Field(gt=0)


class TenantUsageResponse(BaseModel):
    tenant_id: UUID
    used_instances: int
    used_cpu: int
    used_memory_mib: int
    used_disk_gib: int
