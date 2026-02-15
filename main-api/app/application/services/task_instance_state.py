from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.domain.models import Instance, ResourceSpec, TaskCommand
from app.ports.interfaces import InstanceRepository


def apply_pending_instance_state(
    instance_repo: InstanceRepository,
    instance: Instance,
    command: TaskCommand,
    request_payload: dict,
    task_id: UUID,
) -> None:
    if command == "create":
        spec = ResourceSpec(
            cpu=int(request_payload.get("cpu", instance.resource_spec.cpu)),
            memory_mib=int(request_payload.get("memory_mib", instance.resource_spec.memory_mib)),
            disk_gib=int(request_payload.get("disk_gib", instance.resource_spec.disk_gib)),
        )
        instance_repo.update_spec(
            instance.id,
            spec=spec,
            status="creating_pending",
            ip_address=None,
            reserve_resources=True,
            last_task_id=task_id,
            deleted_at=None,
        )
        return

    if command == "update":
        spec = ResourceSpec(
            cpu=int(request_payload.get("cpu", instance.resource_spec.cpu)),
            memory_mib=int(request_payload.get("memory_mib", instance.resource_spec.memory_mib)),
            disk_gib=int(request_payload.get("disk_gib", instance.resource_spec.disk_gib)),
        )
        instance_repo.update_spec(
            instance.id,
            spec=spec,
            status="updating_pending",
            ip_address=instance.ip_address,
            reserve_resources=True,
            last_task_id=task_id,
            deleted_at=instance.deleted_at,
        )
        return

    instance_repo.update_state(
        instance.id,
        status="deleting_pending",
        reserve_resources=False,
        last_task_id=task_id,
        deleted_at=None,
        ip_address=instance.ip_address,
    )


def revert_instance_state_on_terminal_failure(
    instance_repo: InstanceRepository,
    instance_id: UUID,
    command: TaskCommand,
    request_payload: dict,
) -> None:
    if command == "create":
        instance_repo.update_state(
            instance_id,
            status="error",
            reserve_resources=False,
            last_task_id=None,
            deleted_at=None,
            ip_address=None,
        )
        return

    previous_spec = request_payload.get("previous_spec", {})
    spec = ResourceSpec(
        cpu=int(previous_spec.get("cpu", 1)),
        memory_mib=int(previous_spec.get("memory_mib", 512)),
        disk_gib=int(previous_spec.get("disk_gib", 10)),
    )

    if command == "update":
        instance_repo.update_spec(
            instance_id,
            spec=spec,
            status="error",
            ip_address=request_payload.get("previous_ip_address"),
            reserve_resources=True,
            last_task_id=None,
            deleted_at=_parse_timestamp(request_payload.get("previous_deleted_at")),
        )
        return

    instance_repo.update_spec(
        instance_id,
        spec=spec,
        status="error",
        ip_address=request_payload.get("previous_ip_address"),
        reserve_resources=True,
        last_task_id=None,
        deleted_at=None,
    )


def _parse_timestamp(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None
