from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.application.commands.common import TaskAccepted
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.models import InstanceTask
from app.ports.interfaces import CommandOutboxRepository, InstanceRepository, TaskRepository


@dataclass(frozen=True)
class DeleteInstanceCommand:
    instance_id: UUID


class DeleteInstanceHandler:
    def __init__(
        self,
        write_repository: InstanceRepository,
        task_repository: TaskRepository,
        outbox_repository: CommandOutboxRepository,
        outbox_max_attempts: int = 20,
    ):
        self.write_repository = write_repository
        self.task_repository = task_repository
        self.outbox_repository = outbox_repository
        self.outbox_max_attempts = max(1, int(outbox_max_attempts))

    def handle(self, command: DeleteInstanceCommand) -> TaskAccepted:
        instance = self.write_repository.get_for_update(command.instance_id)
        if not instance:
            raise NotFoundError(f"instance {command.instance_id} not found")
        if instance.status == "deleted":
            raise ValidationError("instance is already deleted")
        if self.task_repository.has_active_task(command.instance_id):
            raise ConflictError(f"instance {command.instance_id} already has an active task")

        task_id = uuid4()
        request_id = uuid4()
        now = datetime.now(timezone.utc)

        self.write_repository.update_state(
            command.instance_id,
            status="deleting_pending",
            reserve_resources=False,
            last_task_id=task_id,
            deleted_at=None,
            ip_address=instance.ip_address,
        )

        task = InstanceTask(
            id=task_id,
            instance_id=command.instance_id,
            command="delete",
            status="queued",
            request_id=request_id,
            request_payload={
                "host_node": instance.host_node,
                "previous_spec": {
                    "cpu": instance.resource_spec.cpu,
                    "memory_mib": instance.resource_spec.memory_mib,
                    "disk_gib": instance.resource_spec.disk_gib,
                },
                "previous_ip_address": instance.ip_address,
                "previous_status": instance.status,
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

        self.outbox_repository.enqueue_command(
            topic="instance.delete",
            payload={
                "instance_id": str(command.instance_id),
                "host_node": instance.host_node,
            },
            task_id=task_id,
            request_id=request_id,
            max_attempts=self.outbox_max_attempts,
        )

        return TaskAccepted(
            task_id=task_id,
            instance_id=command.instance_id,
            command="delete",
            status="queued",
            accepted_at=now,
        )
