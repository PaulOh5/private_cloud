from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.application.commands.common import TaskAccepted
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.models import InstanceTask
from app.ports.interfaces import InstanceRepository, TaskRepository, VmProvisioningPort


@dataclass(frozen=True)
class StopInstanceCommand:
    instance_id: UUID


class StopInstanceHandler:
    def __init__(
        self,
        write_repository: InstanceRepository,
        task_repository: TaskRepository,
        provisioning: VmProvisioningPort,
    ):
        self.write_repository = write_repository
        self.task_repository = task_repository
        self.provisioning = provisioning

    def handle(self, command: StopInstanceCommand) -> TaskAccepted:
        instance = self.write_repository.get_for_update(command.instance_id)
        if not instance:
            raise NotFoundError(f"instance {command.instance_id} not found")
        if instance.status == "deleted":
            raise ValidationError("cannot stop a deleted instance")
        if instance.status not in {"running", "stopped"}:
            raise ValidationError(f"cannot stop instance from status {instance.status}")
        if self.task_repository.has_active_task(command.instance_id):
            raise ConflictError(f"instance {command.instance_id} already has an active task")

        task_id = uuid4()
        request_id = uuid4()
        now = datetime.now(timezone.utc)

        self.write_repository.update_state(
            command.instance_id,
            status="stopping_pending",
            reserve_resources=True,
            last_task_id=task_id,
            deleted_at=instance.deleted_at,
            ip_address=instance.ip_address,
        )

        task = InstanceTask(
            id=task_id,
            instance_id=command.instance_id,
            command="stop",
            status="queued",
            request_id=request_id,
            request_payload={
                "host_node": instance.host_node,
                "tenant_id": str(instance.tenant_id),
                "previous_status": instance.status,
                "previous_ip_address": instance.ip_address,
                "previous_reserve_resources": instance.reserve_resources,
            },
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
        self.task_repository.create_task(task)

        self.provisioning.publish_command(
            command="instance.stop",
            payload={
                "instance_id": str(command.instance_id),
                "host_node": instance.host_node,
            },
            task_id=task_id,
            request_id=request_id,
        )

        return TaskAccepted(
            task_id=task_id,
            instance_id=command.instance_id,
            command="stop",
            status="queued",
            accepted_at=now,
        )
