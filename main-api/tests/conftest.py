from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.domain.models import Instance, InstanceTask, ResourceSpec


class InMemoryInstanceRepo:
    def __init__(self):
        self.instances: dict[UUID, Instance] = {}

    def get_for_update(self, instance_id: UUID) -> Instance | None:
        return self.instances.get(instance_id)

    def create(self, instance: Instance) -> Instance:
        self.instances[instance.id] = instance
        return instance

    def update_spec(
        self,
        instance_id: UUID,
        spec: ResourceSpec,
        status: str,
        ip_address: str | None,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
    ) -> Instance:
        current = self.instances[instance_id]
        updated = replace(
            current,
            resource_spec=spec,
            status=status,
            ip_address=ip_address,
            reserve_resources=reserve_resources,
            last_task_id=last_task_id,
            deleted_at=deleted_at,
            updated_at=datetime.now(timezone.utc),
        )
        self.instances[instance_id] = updated
        return updated

    def update_state(
        self,
        instance_id: UUID,
        status: str,
        reserve_resources: bool,
        last_task_id: UUID | None,
        deleted_at,
        ip_address: str | None,
    ) -> Instance:
        current = self.instances[instance_id]
        updated = replace(
            current,
            status=status,
            reserve_resources=reserve_resources,
            last_task_id=last_task_id,
            deleted_at=deleted_at,
            ip_address=ip_address,
            updated_at=datetime.now(timezone.utc),
        )
        self.instances[instance_id] = updated
        return updated


class InMemoryTaskRepo:
    def __init__(self):
        self.tasks: dict[UUID, InstanceTask] = {}

    def has_active_task(self, instance_id: UUID) -> bool:
        return any(
            t.instance_id == instance_id and t.status in {"queued", "running", "cancel_pending"}
            for t in self.tasks.values()
        )

    def create_task(self, task: InstanceTask) -> InstanceTask:
        self.tasks[task.id] = task
        return task

    def get(self, task_id: UUID) -> InstanceTask | None:
        return self.tasks.get(task_id)

    def get_for_update(self, task_id: UUID) -> InstanceTask | None:
        return self.tasks.get(task_id)

    def list(self, limit: int, offset: int, status, instance_id, command, tenant_id=None):
        items = list(self.tasks.values())
        if status:
            items = [t for t in items if t.status == status]
        if instance_id:
            items = [t for t in items if t.instance_id == instance_id]
        if command:
            items = [t for t in items if t.command == command]
        total = len(items)
        return items[offset : offset + limit], total

    def mark_running(self, task_id: UUID, attempt_count: int) -> InstanceTask:
        t = self.tasks[task_id]
        updated = replace(
            t,
            status="running",
            attempt_count=attempt_count,
            started_at=t.started_at or datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.tasks[task_id] = updated
        return updated

    def mark_cancel_pending(
        self,
        task_id: UUID,
        canceled_by: UUID | None,
        cancel_reason: str | None,
    ) -> InstanceTask:
        t = self.tasks[task_id]
        updated = replace(
            t,
            status="cancel_pending",
            updated_at=datetime.now(timezone.utc),
        )
        self.tasks[task_id] = updated
        return updated

    def mark_canceled(
        self,
        task_id: UUID,
        attempt_count: int,
        canceled_by: UUID | None,
        cancel_reason: str | None,
        result_payload: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> InstanceTask:
        t = self.tasks[task_id]
        updated = replace(
            t,
            status="canceled",
            attempt_count=attempt_count,
            result_payload=result_payload,
            error_code=error_code,
            error_message=error_message,
            finished_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.tasks[task_id] = updated
        return updated

    def clone_for_retry(
        self,
        source_task: InstanceTask,
        new_task_id: UUID,
        new_request_id: UUID,
        created_at: datetime,
    ) -> InstanceTask:
        cloned = replace(
            source_task,
            id=new_task_id,
            status="queued",
            request_id=new_request_id,
            result_payload=None,
            error_code=None,
            error_message=None,
            attempt_count=0,
            created_at=created_at,
            started_at=None,
            finished_at=None,
            updated_at=created_at,
        )
        self.tasks[new_task_id] = cloned
        return cloned

    def mark_terminal(
        self,
        task_id: UUID,
        status,
        attempt_count: int,
        result_payload: dict | None,
        error_code: str | None,
        error_message: str | None,
    ) -> InstanceTask:
        t = self.tasks[task_id]
        updated = replace(
            t,
            status=status,
            attempt_count=attempt_count,
            result_payload=result_payload,
            error_code=error_code,
            error_message=error_message,
            finished_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.tasks[task_id] = updated
        return updated


class DummyCapacity:
    def assert_capacity(self, check):
        return None


class DummyProvisioning:
    def __init__(self):
        self.calls: list[dict] = []

    def publish_command(self, command: str, payload: dict, task_id: UUID, request_id: UUID) -> None:
        self.calls.append(
            {
                "command": command,
                "payload": payload,
                "task_id": task_id,
                "request_id": request_id,
            }
        )


@pytest.fixture
def in_memory_instance_repo() -> InMemoryInstanceRepo:
    return InMemoryInstanceRepo()


@pytest.fixture
def in_memory_task_repo() -> InMemoryTaskRepo:
    return InMemoryTaskRepo()


@pytest.fixture
def dummy_capacity() -> DummyCapacity:
    return DummyCapacity()


@pytest.fixture
def dummy_provisioning() -> DummyProvisioning:
    return DummyProvisioning()
