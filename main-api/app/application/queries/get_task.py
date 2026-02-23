from uuid import UUID
from app.domain.errors import NotFoundError
from app.domain.models import InstanceTask
from app.ports import TaskRepository


class GetTaskHandler:
    def __init__(self, task_repository: TaskRepository):
        self.task_repository = task_repository

    async def handle(self, task_id: UUID) -> InstanceTask:
        task = await self.task_repository.get(task_id)
        if not task:
            raise NotFoundError(f"task {task_id} not found")
        return task
