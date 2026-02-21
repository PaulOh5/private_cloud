from __future__ import annotations

from uuid import UUID

from app.ports import CommandOutboxRepository, VmProvisioningPort


class OutboxProvisioningAdapter(VmProvisioningPort):
    def __init__(self, outbox_repository: CommandOutboxRepository, max_attempts: int):
        self.outbox_repository = outbox_repository
        self.max_attempts = max(1, int(max_attempts))

    def publish_command(self, command: str, payload: dict, task_id: UUID, request_id: UUID) -> None:
        self.outbox_repository.enqueue_command(
            topic=command,
            payload=payload,
            task_id=task_id,
            request_id=request_id,
            max_attempts=self.max_attempts,
        )
