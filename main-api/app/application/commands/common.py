from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class TaskAccepted:
    task_id: UUID
    instance_id: UUID
    command: str
    status: str
    accepted_at: datetime
