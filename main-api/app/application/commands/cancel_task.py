from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.application.commands.common import TaskAccepted
from app.application.services.task_instance_state import revert_instance_state_on_terminal_failure
from app.domain.errors import ConflictError, NotFoundError
from app.ports.interfaces import CommandOutboxRepository, InstanceRepository, TaskRepository


@dataclass(frozen=True)
class CancelTaskCommand:
    task_id: UUID
    actor_user_id: UUID | None
    reason: str | None = None


class CancelTaskHandler:
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

    def handle(self, command: CancelTaskCommand) -> TaskAccepted:
        task = self.task_repository.get_for_update(command.task_id)
        if not task:
            raise NotFoundError(f"task {command.task_id} not found")

        instance = self.write_repository.get_for_update(task.instance_id)
        if not instance:
            raise NotFoundError(f"instance {task.instance_id} not found")

        now = datetime.now(timezone.utc)
        if task.status == "queued":
            revert_instance_state_on_terminal_failure(
                instance_repo=self.write_repository,
                instance_id=instance.id,
                command=task.command,
                request_payload=task.request_payload,
            )
            canceled = self.task_repository.mark_canceled(
                task_id=task.id,
                attempt_count=task.attempt_count,
                canceled_by=command.actor_user_id,
                cancel_reason=command.reason,
                result_payload=None,
                error_code="CANCELED",
                error_message=command.reason or "task canceled before execution",
            )
            return TaskAccepted(
                task_id=canceled.id,
                instance_id=canceled.instance_id,
                command=canceled.command,
                status=canceled.status,
                accepted_at=now,
            )

        if task.status == "running":
            cancel_pending = self.task_repository.mark_cancel_pending(
                task_id=task.id,
                canceled_by=command.actor_user_id,
                cancel_reason=command.reason,
            )
            self.outbox_repository.enqueue_command(
                topic="instance.cancel",
                payload={
                    "instance_id": str(instance.id),
                    "target_task_id": str(task.id),
                    "target_command": task.command,
                    "reason": command.reason,
                },
                task_id=task.id,
                request_id=uuid4(),
                max_attempts=self.outbox_max_attempts,
            )
            return TaskAccepted(
                task_id=cancel_pending.id,
                instance_id=cancel_pending.instance_id,
                command=cancel_pending.command,
                status=cancel_pending.status,
                accepted_at=now,
            )

        if task.status in {"cancel_pending", "canceled"}:
            return TaskAccepted(
                task_id=task.id,
                instance_id=task.instance_id,
                command=task.command,
                status=task.status,
                accepted_at=now,
            )

        raise ConflictError(f"task {task.id} cannot be canceled from status {task.status}")
