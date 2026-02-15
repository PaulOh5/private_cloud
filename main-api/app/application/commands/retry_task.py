from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.application.commands.common import TaskAccepted
from app.application.services.task_instance_state import apply_pending_instance_state
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.models import ResourceSpec
from app.ports.interfaces import (
    CapacityCheckInput,
    InstanceRepository,
    ResourceAccountingPort,
    TaskRepository,
    TenantQuotaAccountingPort,
    TenantQuotaCheckInput,
    VmProvisioningPort,
)


@dataclass(frozen=True)
class RetryTaskCommand:
    task_id: UUID


class RetryTaskHandler:
    def __init__(
        self,
        write_repository: InstanceRepository,
        task_repository: TaskRepository,
        provisioning: VmProvisioningPort,
        accounting: ResourceAccountingPort,
        quota_accounting: TenantQuotaAccountingPort | None = None,
    ):
        self.write_repository = write_repository
        self.task_repository = task_repository
        self.provisioning = provisioning
        self.accounting = accounting
        self.quota_accounting = quota_accounting

    def handle(self, command: RetryTaskCommand) -> TaskAccepted:
        source_task = self.task_repository.get_for_update(command.task_id)
        if not source_task:
            raise NotFoundError(f"task {command.task_id} not found")
        if source_task.status not in {"failed", "canceled"}:
            raise ValidationError("only failed or canceled tasks can be retried")

        instance = self.write_repository.get_for_update(source_task.instance_id)
        if not instance:
            raise NotFoundError(f"instance {source_task.instance_id} not found")
        if instance.status == "deleted":
            raise ValidationError("cannot retry task for a deleted instance")
        if self.task_repository.has_active_task(instance.id):
            raise ConflictError(f"instance {instance.id} already has an active task")

        host_node = str(source_task.request_payload.get("host_node") or instance.host_node)
        requested = self._requested_spec(source_task, instance.resource_spec)
        if self.quota_accounting is not None and source_task.command in {"create", "update"}:
            self.quota_accounting.assert_quota(
                TenantQuotaCheckInput(
                    tenant_id=instance.tenant_id,
                    current=instance.resource_spec,
                    requested=requested,
                    current_reserved=instance.reserve_resources,
                    requested_reserved=True,
                )
            )
        if source_task.command == "create":
            self.accounting.assert_capacity(
                CapacityCheckInput(host_node=host_node, current=None, requested=requested)
            )
        if source_task.command == "update":
            self.accounting.assert_capacity(
                CapacityCheckInput(host_node=host_node, current=instance.resource_spec, requested=requested)
            )

        now = datetime.now(timezone.utc)
        new_task_id = uuid4()
        new_request_id = uuid4()

        apply_pending_instance_state(
            instance_repo=self.write_repository,
            instance=instance,
            command=source_task.command,
            request_payload=source_task.request_payload,
            task_id=new_task_id,
        )
        cloned = self.task_repository.clone_for_retry(
            source_task=source_task,
            new_task_id=new_task_id,
            new_request_id=new_request_id,
            created_at=now,
        )

        self.provisioning.publish_command(
            command=f"instance.{source_task.command}",
            payload=self._command_payload(
                command=source_task.command,
                instance_id=instance.id,
                request_payload=source_task.request_payload,
                host_node=host_node,
            ),
            task_id=cloned.id,
            request_id=new_request_id,
        )

        return TaskAccepted(
            task_id=cloned.id,
            instance_id=cloned.instance_id,
            command=cloned.command,
            status=cloned.status,
            accepted_at=now,
        )

    def _requested_spec(self, source_task, fallback: ResourceSpec) -> ResourceSpec:
        payload = source_task.request_payload
        return ResourceSpec(
            cpu=int(payload.get("cpu", fallback.cpu)),
            memory_mib=int(payload.get("memory_mib", fallback.memory_mib)),
            disk_gib=int(payload.get("disk_gib", fallback.disk_gib)),
        )

    def _command_payload(
        self,
        *,
        command: str,
        instance_id: UUID,
        request_payload: dict,
        host_node: str,
    ) -> dict:
        if command == "create":
            payload = {
                "instance_id": str(instance_id),
                "name": request_payload.get("name"),
                "cpu": int(request_payload.get("cpu")),
                "memory_mib": int(request_payload.get("memory_mib")),
                "disk_gib": int(request_payload.get("disk_gib")),
                "host_node": host_node,
            }
            image_id = request_payload.get("image_id")
            if image_id:
                payload["image_id"] = str(image_id)
            return payload

        if command == "update":
            return {
                "instance_id": str(instance_id),
                "cpu": int(request_payload.get("cpu")),
                "memory_mib": int(request_payload.get("memory_mib")),
                "disk_gib": int(request_payload.get("disk_gib")),
                "host_node": host_node,
            }

        return {
            "instance_id": str(instance_id),
            "host_node": host_node,
        }
