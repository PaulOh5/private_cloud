from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.application.commands.common import TaskAccepted
from app.domain.models import Instance, InstanceTask, ResourceSpec
from app.ports import (
    CommandOutboxRepository,
    CapacityCheckInput,
    InstanceRepository,
    ResourceAccountingPort,
    TaskRepository,
    TenantQuotaAccountingPort,
    TenantQuotaCheckInput,
)


@dataclass(frozen=True)
class CreateInstanceCommand:
    cpu: int
    memory_mib: int
    disk_gib: int
    name: str | None
    host_node: str
    image_id: str | None = None
    tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")


class CreateInstanceHandler:
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

    def handle(self, command: CreateInstanceCommand) -> TaskAccepted:
        spec = ResourceSpec(cpu=command.cpu, memory_mib=command.memory_mib, disk_gib=command.disk_gib)
        spec.validate()

        if self.quota_accounting is not None:
            self.quota_accounting.assert_quota(
                TenantQuotaCheckInput(
                    tenant_id=command.tenant_id,
                    current=None,
                    requested=spec,
                    current_profile="none",
                    requested_profile="running",
                )
            )

        self.accounting.assert_capacity(
            CapacityCheckInput(
                host_node=command.host_node,
                current=None,
                requested=spec,
                current_profile="none",
                requested_profile="running",
            )
        )

        instance_id = uuid4()
        task_id = uuid4()
        request_id = uuid4()
        now = datetime.now(timezone.utc)

        instance = Instance(
            id=UUID(str(instance_id)),
            tenant_id=command.tenant_id,
            name=command.name,
            resource_spec=spec,
            status="creating_pending",
            ip_address=None,
            host_node=command.host_node,
            reserve_resources=True,
            last_task_id=task_id,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
        self.write_repository.create(instance)

        task = InstanceTask(
            id=task_id,
            instance_id=instance_id,
            command="create",
            status="queued",
            request_id=request_id,
            request_payload={
                "name": command.name,
                "cpu": spec.cpu,
                "memory_mib": spec.memory_mib,
                "disk_gib": spec.disk_gib,
                "host_node": command.host_node,
                "tenant_id": str(command.tenant_id),
                **({"image_id": command.image_id} if command.image_id else {}),
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
            topic="instance.create",
            payload={
                "instance_id": str(instance_id),
                "name": command.name,
                "cpu": spec.cpu,
                "memory_mib": spec.memory_mib,
                "disk_gib": spec.disk_gib,
                "host_node": command.host_node,
                **({"image_id": command.image_id} if command.image_id else {}),
            },
            task_id=task_id,
            request_id=request_id,
            max_attempts=self.outbox_max_attempts,
        )

        return TaskAccepted(
            task_id=task_id,
            instance_id=instance_id,
            command="create",
            status="queued",
            accepted_at=now,
        )
