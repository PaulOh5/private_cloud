from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
