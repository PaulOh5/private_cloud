from dataclasses import dataclass
from uuid import UUID

from app.domain.models import InstanceTask, TaskCommand, TaskStatus
from app.ports.interfaces import TaskRepository


@dataclass(frozen=True)
class ListTasksQuery:
    limit: int
    offset: int
    status: TaskStatus | None = None
    instance_id: UUID | None = None
    command: TaskCommand | None = None


@dataclass(frozen=True)
class ListTasksResult:
    items: list[InstanceTask]
    total: int


class ListTasksHandler:
    def __init__(self, task_repository: TaskRepository):
        self.task_repository = task_repository

    def handle(self, query: ListTasksQuery) -> ListTasksResult:
        items, total = self.task_repository.list(
            limit=query.limit,
            offset=query.offset,
            status=query.status,
            instance_id=query.instance_id,
            command=query.command,
        )
        return ListTasksResult(items=items, total=total)
