from uuid import UUID

from app.domain.errors import NotFoundError
from app.domain.models import Instance
from app.ports import InstanceReadRepository


class GetInstanceHandler:
    def __init__(self, read_repository: InstanceReadRepository):
        self.read_repository = read_repository

    def handle(self, instance_id: UUID) -> Instance:
        instance = self.read_repository.get(instance_id)
        if not instance:
            raise NotFoundError(f"instance {instance_id} not found")
        return instance
