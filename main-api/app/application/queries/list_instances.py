from dataclasses import dataclass
from uuid import UUID

from app.domain.models import Instance
from app.ports import InstanceReadRepository


@dataclass(frozen=True)
class ListInstancesQuery:
    limit: int
    offset: int
    status: str | None = None
    name: str | None = None
    tenant_id: UUID | None = None


@dataclass(frozen=True)
class ListInstancesResult:
    items: list[Instance]
    total: int


class ListInstancesHandler:
    def __init__(self, read_repository: InstanceReadRepository):
        self.read_repository = read_repository

    def handle(self, query: ListInstancesQuery) -> ListInstancesResult:
        items, total = self.read_repository.list(
            limit=query.limit,
            offset=query.offset,
            status=query.status,
            name=query.name,
            tenant_id=query.tenant_id,
        )
        return ListInstancesResult(items=items, total=total)
