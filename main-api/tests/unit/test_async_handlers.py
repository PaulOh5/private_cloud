from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.application.commands.create_instance import CreateInstanceCommand, CreateInstanceHandler
from app.application.commands.delete_instance import DeleteInstanceCommand, DeleteInstanceHandler
from app.application.commands.update_instance import UpdateInstanceCommand, UpdateInstanceHandler
from app.domain.errors import ConflictError
from app.domain.models import Instance, InstanceTask, ResourceSpec


def test_create_handler_queues_task_and_publishes(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
    dummy_capacity,
):
    handler = CreateInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        provisioning=dummy_provisioning,
        accounting=dummy_capacity,
    )

    accepted = handler.handle(
        CreateInstanceCommand(
            cpu=2,
            memory_mib=2048,
            disk_gib=20,
            name="vm-a",
            host_node="localhost",
        )
    )

    assert accepted.status == "queued"
    assert accepted.command == "create"
    assert accepted.instance_id in in_memory_instance_repo.instances
    created_instance = in_memory_instance_repo.instances[accepted.instance_id]
    assert created_instance.status == "creating_pending"
    assert created_instance.reserve_resources is True
    assert accepted.task_id in in_memory_task_repo.tasks
    assert len(dummy_provisioning.calls) == 1
    assert dummy_provisioning.calls[0]["command"] == "instance.create"


def test_update_handler_rejects_when_active_task_exists(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
    dummy_capacity,
):
    instance_id = uuid4()
    existing_task_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-b",
            resource_spec=ResourceSpec(cpu=1, memory_mib=1024, disk_gib=20),
            status="running",
            ip_address="172.30.10.10",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_task_repo.create_task(
        InstanceTask(
            id=existing_task_id,
            instance_id=instance_id,
            command="update",
            status="queued",
            request_id=uuid4(),
            request_payload={},
            result_payload=None,
            error_code=None,
            error_message=None,
            attempt_count=0,
            max_attempts=3,
            created_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
    )

    handler = UpdateInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        provisioning=dummy_provisioning,
        accounting=dummy_capacity,
    )

    with pytest.raises(ConflictError):
        handler.handle(
            UpdateInstanceCommand(
                instance_id=instance_id,
                cpu=2,
                memory_mib=2048,
                disk_gib=30,
                host_node="localhost",
            )
        )


def test_delete_handler_marks_pending_and_publishes(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
):
    instance_id = uuid4()
    now = datetime.now(timezone.utc)
    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-c",
            resource_spec=ResourceSpec(cpu=1, memory_mib=1024, disk_gib=20),
            status="running",
            ip_address="172.30.11.10",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )

    handler = DeleteInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        provisioning=dummy_provisioning,
    )

    accepted = handler.handle(DeleteInstanceCommand(instance_id=instance_id))

    assert accepted.command == "delete"
    updated = in_memory_instance_repo.instances[instance_id]
    assert updated.status == "deleting_pending"
    assert updated.reserve_resources is False
    assert len(dummy_provisioning.calls) == 1
    assert dummy_provisioning.calls[0]["command"] == "instance.delete"
