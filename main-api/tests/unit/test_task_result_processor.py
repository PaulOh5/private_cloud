from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.application.services.task_result_processor import (
    TaskResultProcessor,
    VmResultEvent,
)
from app.domain.models import Instance, InstanceTask, ResourceSpec


@pytest.mark.asyncio
async def test_result_processor_create_success_sets_instance_running(
    in_memory_instance_repo,
    in_memory_task_repo,
):
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-success",
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
            request_id=request_id,
            request_payload={"cpu": 1, "memory_mib": 1024, "disk_gib": 20},
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

    processor = TaskResultProcessor(in_memory_instance_repo, in_memory_task_repo)
    await processor.process(
        VmResultEvent(
            task_id=task_id,
            request_id=request_id,
            instance_id=instance_id,
            command="create",
            status="succeeded",
            attempt_count=1,
            result={"ip_address": "172.30.50.10", "status": "running"},
            error_code=None,
            error_message=None,
            timestamp=datetime.now(timezone.utc),
        )
    )

    task = in_memory_task_repo.tasks[task_id]
    instance = in_memory_instance_repo.instances[instance_id]
    assert task.status == "succeeded"
    assert instance.status == "running"
    assert instance.ip_address == "172.30.50.10"


@pytest.mark.asyncio
async def test_result_processor_update_failed_rolls_back_spec(
    in_memory_instance_repo,
    in_memory_task_repo,
):
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-fail",
            resource_spec=ResourceSpec(cpu=4, memory_mib=8192, disk_gib=40),
            status="updating_pending",
            ip_address="172.30.60.10",
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
            request_id=request_id,
            request_payload={
                "previous_spec": {"cpu": 2, "memory_mib": 4096, "disk_gib": 30},
                "previous_ip_address": "172.30.60.10",
                "previous_deleted_at": None,
            },
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

    processor = TaskResultProcessor(in_memory_instance_repo, in_memory_task_repo)
    await processor.process(
        VmResultEvent(
            task_id=task_id,
            request_id=request_id,
            instance_id=instance_id,
            command="update",
            status="failed",
            attempt_count=3,
            result=None,
            error_code="QEMU_ERROR",
            error_message="boom",
            timestamp=datetime.now(timezone.utc),
        )
    )

    task = in_memory_task_repo.tasks[task_id]
    instance = in_memory_instance_repo.instances[instance_id]
    assert task.status == "failed"
    assert task.error_code == "QEMU_ERROR"
    assert instance.status == "error"
    assert instance.resource_spec.cpu == 2
    assert instance.resource_spec.memory_mib == 4096
    assert instance.resource_spec.disk_gib == 30


@pytest.mark.asyncio
async def test_result_processor_canceled_marks_task_canceled(
    in_memory_instance_repo,
    in_memory_task_repo,
):
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-canceled",
            resource_spec=ResourceSpec(cpu=4, memory_mib=8192, disk_gib=40),
            status="updating_pending",
            ip_address="172.30.60.10",
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
            status="cancel_pending",
            request_id=request_id,
            request_payload={
                "previous_spec": {"cpu": 2, "memory_mib": 4096, "disk_gib": 30},
                "previous_ip_address": "172.30.60.10",
                "previous_deleted_at": None,
            },
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

    processor = TaskResultProcessor(in_memory_instance_repo, in_memory_task_repo)
    await processor.process(
        VmResultEvent(
            task_id=task_id,
            request_id=request_id,
            instance_id=instance_id,
            command="cancel",
            status="canceled",
            attempt_count=1,
            result={"status": "canceled"},
            error_code=None,
            error_message=None,
            timestamp=datetime.now(timezone.utc),
        )
    )

    task = in_memory_task_repo.tasks[task_id]
    instance = in_memory_instance_repo.instances[instance_id]
    assert task.status == "canceled"
    assert instance.status == "error"
    assert instance.resource_spec.cpu == 2


@pytest.mark.asyncio
async def test_result_processor_ignores_running_event_for_cancel_pending(
    in_memory_instance_repo,
    in_memory_task_repo,
):
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-cancel-running-ignore",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="updating_pending",
            ip_address="172.30.10.10",
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
            status="cancel_pending",
            request_id=request_id,
            request_payload={},
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

    processor = TaskResultProcessor(in_memory_instance_repo, in_memory_task_repo)
    await processor.process(
        VmResultEvent(
            task_id=task_id,
            request_id=request_id,
            instance_id=instance_id,
            command="cancel",
            status="running",
            attempt_count=1,
            result=None,
            error_code=None,
            error_message=None,
            timestamp=datetime.now(timezone.utc),
        )
    )

    assert in_memory_task_repo.tasks[task_id].status == "cancel_pending"


@pytest.mark.asyncio
async def test_result_processor_update_success_keeps_stopped_when_result_status_is_stopped(
    in_memory_instance_repo,
    in_memory_task_repo,
):
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-update-stopped",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="updating_pending",
            ip_address="172.30.70.10",
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
            request_id=request_id,
            request_payload={"previous_ip_address": "172.30.70.10"},
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

    processor = TaskResultProcessor(in_memory_instance_repo, in_memory_task_repo)
    await processor.process(
        VmResultEvent(
            task_id=task_id,
            request_id=request_id,
            instance_id=instance_id,
            command="update",
            status="succeeded",
            attempt_count=1,
            result={"status": "stopped", "ip_address": "172.30.70.10"},
            error_code=None,
            error_message=None,
            timestamp=datetime.now(timezone.utc),
        )
    )
    assert in_memory_instance_repo.instances[instance_id].status == "stopped"
    assert in_memory_task_repo.tasks[task_id].status == "succeeded"


@pytest.mark.asyncio
async def test_result_processor_stop_failed_rolls_back_to_running(
    in_memory_instance_repo,
    in_memory_task_repo,
):
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-stop-fail",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="stopping_pending",
            ip_address="172.30.80.10",
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
            command="stop",
            status="running",
            request_id=request_id,
            request_payload={
                "previous_status": "running",
                "previous_ip_address": "172.30.80.10",
                "previous_reserve_resources": True,
            },
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

    processor = TaskResultProcessor(in_memory_instance_repo, in_memory_task_repo)
    await processor.process(
        VmResultEvent(
            task_id=task_id,
            request_id=request_id,
            instance_id=instance_id,
            command="stop",
            status="failed",
            attempt_count=1,
            result=None,
            error_code="QEMU_ERROR",
            error_message="failed",
            timestamp=datetime.now(timezone.utc),
        )
    )
    assert in_memory_instance_repo.instances[instance_id].status == "running"
    assert in_memory_task_repo.tasks[task_id].status == "failed"


@pytest.mark.asyncio
async def test_result_processor_start_failed_rolls_back_to_stopped(
    in_memory_instance_repo,
    in_memory_task_repo,
):
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    now = datetime.now(timezone.utc)

    in_memory_instance_repo.create(
        Instance(
            id=instance_id,
            name="vm-start-fail",
            resource_spec=ResourceSpec(cpu=2, memory_mib=2048, disk_gib=30),
            status="starting_pending",
            ip_address="172.30.90.10",
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
            request_id=request_id,
            request_payload={
                "previous_status": "stopped",
                "previous_ip_address": "172.30.90.10",
                "previous_reserve_resources": True,
            },
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

    processor = TaskResultProcessor(in_memory_instance_repo, in_memory_task_repo)
    await processor.process(
        VmResultEvent(
            task_id=task_id,
            request_id=request_id,
            instance_id=instance_id,
            command="start",
            status="failed",
            attempt_count=1,
            result=None,
            error_code="QEMU_ERROR",
            error_message="failed",
            timestamp=datetime.now(timezone.utc),
        )
    )
    assert in_memory_instance_repo.instances[instance_id].status == "stopped"
    assert in_memory_task_repo.tasks[task_id].status == "failed"
