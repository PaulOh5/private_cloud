from __future__ import annotations

from app.api.schemas import InstanceResponse, TaskResponse


def to_instance_response(instance) -> InstanceResponse:
    return InstanceResponse(
        id=instance.id,
        name=instance.name,
        cpu=instance.resource_spec.cpu,
        memory_mib=instance.resource_spec.memory_mib,
        disk_gib=instance.resource_spec.disk_gib,
        status=instance.status,
        ip_address=instance.ip_address,
        host_node=instance.host_node,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


def to_task_response(task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        instance_id=task.instance_id,
        command=task.command,
        status=task.status,
        request_id=task.request_id,
        request_payload=task.request_payload,
        result_payload=task.result_payload,
        error_code=task.error_code,
        error_message=task.error_message,
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        updated_at=task.updated_at,
    )
