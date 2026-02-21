from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.application.commands.common import TaskAccepted
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.models import InstanceTask
from app.ports.interfaces import (
    CapacityCheckInput,
    CommandOutboxRepository,
    InstanceRepository,
    ResourceAccountingPort,
    TaskRepository,
    TenantQuotaAccountingPort,
    TenantQuotaCheckInput,
)


@dataclass(frozen=True)
class StartInstanceCommand:
    instance_id: UUID
    host_node: str


class StartInstanceHandler:
    def __init__(
        self,
        write_repository: InstanceRepository,
        task_repository: TaskRepository,
        outbox_repository: CommandOutboxRepository,
        accounting: ResourceAccountingPort,
        quota_accounting: TenantQuotaAccountingPort | None = None,
        outbox_max_attempts: int = 20,
    ):
        self.write_repository = write_repository
        self.task_repository = task_repository
        self.outbox_repository = outbox_repository
        self.outbox_max_attempts = max(1, int(outbox_max_attempts))
        self.accounting = accounting
        self.quota_accounting = quota_accounting

    def handle(self, command: StartInstanceCommand) -> TaskAccepted:
        instance = self.write_repository.get_for_update(command.instance_id)
        if not instance:
            raise NotFoundError(f"instance {command.instance_id} not found")
        if instance.status == "deleted":
            raise ValidationError("cannot start a deleted instance")
        if instance.status not in {"running", "stopped"}:
            raise ValidationError(f"cannot start instance from status {instance.status}")
        if self.task_repository.has_active_task(command.instance_id):
            raise ConflictError(f"instance {command.instance_id} already has an active task")

        # Keep idempotent start (already running) lightweight: do not re-validate quotas/capacity.
        if instance.status == "stopped":
            if self.quota_accounting is not None:
                self.quota_accounting.assert_quota(
                    TenantQuotaCheckInput(
                        tenant_id=instance.tenant_id,
                        current=instance.resource_spec,
                        requested=instance.resource_spec,
                        current_profile="stopped",
                        requested_profile="running",
                    )
                )
            self.accounting.assert_capacity(
                CapacityCheckInput(
                    host_node=command.host_node,
                    current=instance.resource_spec,
                    requested=instance.resource_spec,
                    current_profile="stopped",
                    requested_profile="running",
                )
            )

        task_id = uuid4()
        request_id = uuid4()
        now = datetime.now(timezone.utc)

        self.write_repository.update_state(
            command.instance_id,
            status="starting_pending",
            reserve_resources=True,
            last_task_id=task_id,
            deleted_at=instance.deleted_at,
            ip_address=instance.ip_address,
        )

        task = InstanceTask(
            id=task_id,
            instance_id=command.instance_id,
            command="start",
            status="queued",
            request_id=request_id,
            request_payload={
                "host_node": command.host_node,
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

        self.outbox_repository.enqueue_command(
            topic="instance.start",
            payload={
                "instance_id": str(command.instance_id),
                "host_node": command.host_node,
            },
            task_id=task_id,
            request_id=request_id,
            max_attempts=self.outbox_max_attempts,
        )

        return TaskAccepted(
            task_id=task_id,
            instance_id=command.instance_id,
            command="start",
            status="queued",
            accepted_at=now,
        )
