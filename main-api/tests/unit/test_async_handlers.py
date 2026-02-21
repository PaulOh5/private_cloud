from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.application.commands.cancel_task import CancelTaskCommand, CancelTaskHandler
from app.application.commands.create_instance import CreateInstanceCommand, CreateInstanceHandler
from app.application.commands.delete_instance import DeleteInstanceCommand, DeleteInstanceHandler
from app.application.commands.retry_task import RetryTaskCommand, RetryTaskHandler
from app.application.commands.start_instance import StartInstanceCommand, StartInstanceHandler
from app.application.commands.stop_instance import StopInstanceCommand, StopInstanceHandler
from app.application.commands.update_instance import UpdateInstanceCommand, UpdateInstanceHandler
from app.domain.errors import CapacityExceededError, ConflictError, QuotaExceededError
from app.domain.models import Instance, InstanceTask, ResourceSpec


class SpyCapacity:
    def __init__(self):
        self.calls: list = []

    def assert_capacity(self, check):
        self.calls.append(check)


class SpyQuota:
    def __init__(self):
        self.calls: list = []

    def assert_quota(self, check):
        self.calls.append(check)


class FailingQuota:
    def assert_quota(self, _check):
        raise QuotaExceededError("quota exceeded")


class FailingCapacity:
    def assert_capacity(self, _check):
        raise CapacityExceededError("capacity exceeded")


def test_create_handler_queues_task_and_publishes(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
    dummy_capacity,
):
    handler = CreateInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        outbox_repository=dummy_provisioning,
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


def test_create_handler_forwards_optional_image_id(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
    dummy_capacity,
):
    handler = CreateInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        outbox_repository=dummy_provisioning,
        accounting=dummy_capacity,
    )

    accepted = handler.handle(
        CreateInstanceCommand(
            cpu=2,
            memory_mib=2048,
            disk_gib=20,
            name="vm-image",
            host_node="localhost",
            image_id="ubuntu-22.04",
        )
    )

    assert accepted.status == "queued"
    assert dummy_provisioning.calls[0]["payload"]["image_id"] == "ubuntu-22.04"
    assert in_memory_task_repo.tasks[accepted.task_id].request_payload["image_id"] == "ubuntu-22.04"


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
        outbox_repository=dummy_provisioning,
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
        outbox_repository=dummy_provisioning,
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
                "image_id": "ubuntu-24.04",
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
        outbox_repository=dummy_provisioning,
        accounting=dummy_capacity,
    )
    accepted = handler.handle(RetryTaskCommand(task_id=failed_task_id))

    assert accepted.task_id != failed_task_id
    assert accepted.status == "queued"
    assert accepted.command == "create"
    assert in_memory_task_repo.tasks[accepted.task_id].status == "queued"
    assert in_memory_instance_repo.instances[instance_id].status == "creating_pending"
    assert dummy_provisioning.calls[-1]["command"] == "instance.create"
    assert dummy_provisioning.calls[-1]["payload"]["image_id"] == "ubuntu-24.04"


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
        outbox_repository=dummy_provisioning,
        accounting=dummy_capacity,
    )
    with pytest.raises(ConflictError):
        handler.handle(RetryTaskCommand(task_id=failed_task_id))


def test_update_handler_on_stopped_sets_boot_after_update_false(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
    dummy_capacity,
):
    instance_id = uuid4()
    now = datetime.now(timezone.utc)
    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-update-stopped",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="stopped",
            ip_address="172.30.20.10",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    handler = UpdateInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        outbox_repository=dummy_provisioning,
        accounting=dummy_capacity,
    )
    accepted = handler.handle(
        UpdateInstanceCommand(
            instance_id=instance_id,
            cpu=3,
            memory_mib=3072,
            disk_gib=35,
            host_node="localhost",
        )
    )

    assert accepted.command == "update"
    assert in_memory_instance_repo.instances[instance_id].status == "updating_pending"
    assert dummy_provisioning.calls[0]["payload"]["boot_after_update"] is False


def test_start_handler_stopped_performs_quota_capacity_checks_and_publishes(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
):
    instance_id = uuid4()
    now = datetime.now(timezone.utc)
    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-start",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="stopped",
            ip_address="172.30.30.10",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    quota = SpyQuota()
    capacity = SpyCapacity()
    handler = StartInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        outbox_repository=dummy_provisioning,
        accounting=capacity,
        quota_accounting=quota,
    )
    accepted = handler.handle(StartInstanceCommand(instance_id=instance_id, host_node="localhost"))

    assert accepted.command == "start"
    assert accepted.status == "queued"
    assert in_memory_instance_repo.instances[instance_id].status == "starting_pending"
    assert len(quota.calls) == 1
    assert len(capacity.calls) == 1
    assert dummy_provisioning.calls[0]["command"] == "instance.start"


def test_start_handler_quota_exceeded_raises(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
    dummy_capacity,
):
    instance_id = uuid4()
    now = datetime.now(timezone.utc)
    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-start-quota",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="stopped",
            ip_address="172.30.30.10",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    handler = StartInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        outbox_repository=dummy_provisioning,
        accounting=dummy_capacity,
        quota_accounting=FailingQuota(),
    )
    with pytest.raises(QuotaExceededError):
        handler.handle(StartInstanceCommand(instance_id=instance_id, host_node="localhost"))


def test_start_handler_capacity_exceeded_raises(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
):
    instance_id = uuid4()
    now = datetime.now(timezone.utc)
    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-start-capacity",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="stopped",
            ip_address="172.30.30.10",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    handler = StartInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        outbox_repository=dummy_provisioning,
        accounting=FailingCapacity(),
        quota_accounting=None,
    )
    with pytest.raises(CapacityExceededError):
        handler.handle(StartInstanceCommand(instance_id=instance_id, host_node="localhost"))


def test_stop_handler_running_marks_pending_and_publishes(
    in_memory_instance_repo,
    in_memory_task_repo,
    dummy_provisioning,
):
    instance_id = uuid4()
    now = datetime.now(timezone.utc)
    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-stop",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="running",
            ip_address="172.30.30.10",
            host_node="localhost",
            reserve_resources=True,
            last_task_id=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    handler = StopInstanceHandler(
        write_repository=in_memory_instance_repo,
        task_repository=in_memory_task_repo,
        outbox_repository=dummy_provisioning,
    )
    accepted = handler.handle(StopInstanceCommand(instance_id=instance_id))

    assert accepted.command == "stop"
    assert accepted.status == "queued"
    assert in_memory_instance_repo.instances[instance_id].status == "stopping_pending"
    assert dummy_provisioning.calls[0]["command"] == "instance.stop"


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
        outbox_repository=dummy_provisioning,
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
        outbox_repository=dummy_provisioning,
    )
    accepted = handler.handle(CancelTaskCommand(task_id=task_id, actor_user_id=uuid4(), reason="stop"))

    assert accepted.status == "cancel_pending"
    assert in_memory_task_repo.tasks[task_id].status == "cancel_pending"
    assert len(dummy_provisioning.calls) == 1
    assert dummy_provisioning.calls[0]["command"] == "instance.cancel"
    assert dummy_provisioning.calls[0]["task_id"] == task_id


def test_cancel_handler_running_start_task_is_supported(
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
            name="vm-cancel-start",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="starting_pending",
            ip_address="172.30.40.10",
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
            command="start",
            status="running",
            request_id=uuid4(),
            request_payload={"host_node": "localhost"},
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
        outbox_repository=dummy_provisioning,
    )
    accepted = handler.handle(CancelTaskCommand(task_id=task_id, actor_user_id=uuid4(), reason="stop request"))
    assert accepted.status == "cancel_pending"
    assert dummy_provisioning.calls[0]["command"] == "instance.cancel"


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
        outbox_repository=dummy_provisioning,
    )
    accepted = handler.handle(CancelTaskCommand(task_id=task_id, actor_user_id=uuid4(), reason="repeat"))

    assert accepted.status == "cancel_pending"
    assert dummy_provisioning.calls == []
