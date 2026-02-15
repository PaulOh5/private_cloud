from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.application.commands.cancel_task import CancelTaskCommand, CancelTaskHandler
from app.application.commands.create_instance import CreateInstanceCommand, CreateInstanceHandler
from app.application.commands.delete_instance import DeleteInstanceCommand, DeleteInstanceHandler
from app.application.commands.retry_task import RetryTaskCommand, RetryTaskHandler
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


def test_retry_handler_from_failed_creates_new_task_and_publishes(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
    dummy_capacity,
):
    instance_id = uuid4()
    failed_task_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-retry",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="error",
            ip_address=None,
            host_node="localhost",
            reserve_resources=False,
            last_task_id=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_task_repo.create_task(
        InstanceTask(
            id=failed_task_id,
            instance_id=instance_id,
            command="create",
            status="failed",
            request_id=uuid4(),
            request_payload={
                "name": "vm-retry",
                "cpu": 2,
                "memory_mib": 2048,
                "disk_gib": 30,
                "host_node": "localhost",
            },
            result_payload=None,
            error_code="QEMU_ERROR",
            error_message="boom",
            attempt_count=1,
            max_attempts=3,
            created_at=now,
            started_at=now,
            finished_at=now,
            updated_at=now,
        )
    )

    handler = RetryTaskHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        provisioning=dummy_provisioning,
        accounting=dummy_capacity,
    )
    accepted = handler.handle(RetryTaskCommand(task_id=failed_task_id))

    assert accepted.task_id != failed_task_id
    assert accepted.status == "queued"
    assert accepted.command == "create"
    assert in_memory_task_repo.tasks[accepted.task_id].status == "queued"
    assert in_memory_instance_repo.instances[instance_id].status == "creating_pending"
    assert dummy_provisioning.calls[-1]["command"] == "instance.create"


def test_retry_handler_blocked_when_active_task_exists(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
    dummy_capacity,
):
    instance_id = uuid4()
    failed_task_id = uuid4()
    active_task_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-retry-conflict",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="running",
            ip_address="172.30.10.20",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=active_task_id,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_task_repo.create_task(
        InstanceTask(
            id=failed_task_id,
            instance_id=instance_id,
            command="update",
            status="failed",
            request_id=uuid4(),
            request_payload={"cpu": 3, "memory_mib": 3072, "disk_gib": 35, "host_node": "localhost"},
            result_payload=None,
            error_code="QEMU_ERROR",
            error_message="boom",
            attempt_count=1,
            max_attempts=3,
            created_at=now,
            started_at=now,
            finished_at=now,
            updated_at=now,
        )
    )
    in_memory_task_repo.create_task(
        InstanceTask(
            id=active_task_id,
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

    handler = RetryTaskHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        provisioning=dummy_provisioning,
        accounting=dummy_capacity,
    )
    with pytest.raises(ConflictError):
        handler.handle(RetryTaskCommand(task_id=failed_task_id))


def test_cancel_handler_queued_marks_canceled(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
):
    instance_id = uuid4()
    task_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-cancel-queued",
            resource_spec=ResourceSpec(cpu=1, memory_mib=1024, disk_gib=20),
            status="creating_pending",
            ip_address=None,
            host_node="localhost",
            reserve_resources=True,
            last_task_id=task_id,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_task_repo.create_task(
        InstanceTask(
            id=task_id,
            instance_id=instance_id,
            command="create",
            status="queued",
            request_id=uuid4(),
            request_payload={"cpu": 1, "memory_mib": 1024, "disk_gib": 20, "host_node": "localhost"},
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

    handler = CancelTaskHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        provisioning=dummy_provisioning,
    )
    accepted = handler.handle(CancelTaskCommand(task_id=task_id, actor_user_id=uuid4(), reason="user requested"))

    assert accepted.status == "canceled"
    assert in_memory_task_repo.tasks[task_id].status == "canceled"
    assert in_memory_instance_repo.instances[instance_id].status == "error"
    assert dummy_provisioning.calls == []


def test_cancel_handler_running_sets_cancel_pending_and_publishes(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
):
    instance_id = uuid4()
    task_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-cancel-running",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="updating_pending",
            ip_address="172.30.20.20",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=task_id,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    in_memory_task_repo.create_task(
        InstanceTask(
            id=task_id,
            instance_id=instance_id,
            command="update",
            status="running",
            request_id=uuid4(),
            request_payload={"cpu": 2, "memory_mib": 2048, "disk_gib": 30, "host_node": "localhost"},
            result_payload=None,
            error_code=None,
            error_message=None,
            attempt_count=1,
            max_attempts=3,
            created_at=now,
            started_at=now,
            finished_at=None,
            updated_at=now,
        )
    )

    handler = CancelTaskHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        provisioning=dummy_provisioning,
    )
    accepted = handler.handle(CancelTaskCommand(task_id=task_id, actor_user_id=uuid4(), reason="stop"))

    assert accepted.status == "cancel_pending"
    assert in_memory_task_repo.tasks[task_id].status == "cancel_pending"
    assert len(dummy_provisioning.calls) == 1
    assert dummy_provisioning.calls[0]["command"] == "instance.cancel"
    assert dummy_provisioning.calls[0]["task_id"] == task_id


def test_cancel_handler_duplicate_cancel_is_idempotent(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
):
    instance_id = uuid4()
    task_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-cancel-idempotent",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="error",
            ip_address=None,
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
            id=task_id,
            instance_id=instance_id,
            command="update",
            status="cancel_pending",
            request_id=uuid4(),
            request_payload={"cpu": 2, "memory_mib": 2048, "disk_gib": 30, "host_node": "localhost"},
            result_payload=None,
            error_code=None,
            error_message=None,
            attempt_count=1,
            max_attempts=3,
            created_at=now,
            started_at=now,
            finished_at=None,
            updated_at=now,
        )
    )

    handler = CancelTaskHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        provisioning=dummy_provisioning,
    )
    accepted = handler.handle(CancelTaskCommand(task_id=task_id, actor_user_id=uuid4(), reason="repeat"))

    assert accepted.status == "cancel_pending"
    assert dummy_provisioning.calls == []
