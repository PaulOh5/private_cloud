from datetime import datetime, timezone
from uuid import uuid4

from app.application.services.task_result_processor import TaskResultProcessor, VmResultEvent
from app.domain.models import Instance, InstanceTask, ResourceSpec


def test_result_processor_create_success_sets_instance_running(
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
    processor.process(
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


def test_result_processor_update_failed_rolls_back_spec(
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
    processor.process(
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
