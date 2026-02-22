from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.application.commands.common import TaskAccepted
from app.application.services.task_instance_state import apply_pending_instance_state, revert_instance_state_on_terminal_failure
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.models import ResourceSpec
from app.ports import (
    CapacityCheckInput,
    CommandOutboxRepository,
    InstanceRepository,
    ResourceAccountingPort,
    TaskRepository,
    TenantQuotaAccountingPort,
    TenantQuotaCheckInput,
)


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


@dataclass(frozen=True)
class RetryTaskCommand:
    task_id: UUID


class RetryTaskHandler:
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
        current_profile = self._profile_for_instance(instance.status, instance.reserve_resources)
        requested_profile = self._requested_profile(source_task.command, source_task.request_payload)
        if self.quota_accounting is not None and source_task.command in {"create", "update", "start"}:
            self.quota_accounting.assert_quota(
                TenantQuotaCheckInput(
                    tenant_id=instance.tenant_id,
                    current=instance.resource_spec,
                    requested=requested,
                    current_profile=current_profile,
                    requested_profile=requested_profile,
                )
            )
        if source_task.command in {"create", "update", "start"}:
            self.accounting.assert_capacity(
                CapacityCheckInput(
                    host_node=host_node,
                    current=instance.resource_spec,
                    requested=requested,
                    current_profile=current_profile,
                    requested_profile=requested_profile,
                )
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

        self.outbox_repository.enqueue_command(
            topic=f"instance.{source_task.command}",
            payload=self._command_payload(
                command=source_task.command,
                instance_id=instance.id,
                request_payload=source_task.request_payload,
                host_node=host_node,
            ),
            task_id=cloned.id,
            request_id=new_request_id,
            max_attempts=self.outbox_max_attempts,
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

    def _profile_for_instance(self, status: str, reserve_resources: bool) -> str:
        if not reserve_resources:
            return "none"
        if status == "stopped":
            return "stopped"
        return "running"

    def _requested_profile(self, command: str, request_payload: dict) -> str:
        if command == "stop":
            return "stopped"
        if command == "update" and not bool(request_payload.get("boot_after_update", True)):
            return "stopped"
        if command in {"create", "update", "start"}:
            return "running"
        return "none"

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
            payload = {
                "instance_id": str(instance_id),
                "cpu": int(request_payload.get("cpu")),
                "memory_mib": int(request_payload.get("memory_mib")),
                "disk_gib": int(request_payload.get("disk_gib")),
                "host_node": host_node,
            }
            payload["boot_after_update"] = bool(request_payload.get("boot_after_update", True))
            return payload

        return {
            "instance_id": str(instance_id),
            "host_node": host_node,
        }
