from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.domain.errors import NotFoundError
from app.domain.models import ResourceSpec
from app.ports.interfaces import InstanceRepository, TaskRepository


class RetryableResultEventError(Exception):
    pass


@dataclass(frozen=True)
class VmResultEvent:
    task_id: UUID
    request_id: UUID
    instance_id: UUID
    command: str
    status: str
    attempt_count: int
    result: dict | None
    error_code: str | None
    error_message: str | None
    timestamp: datetime


class TaskResultProcessor:
    def __init__(self, instance_repo: InstanceRepository, task_repo: TaskRepository):
        self.instance_repo = instance_repo
        self.task_repo = task_repo

    def process(self, event: VmResultEvent) -> None:
        task = self.task_repo.get_for_update(event.task_id)
        if not task:
            now = datetime.now(timezone.utc)
            if (now - event.timestamp).total_seconds() < 60:
                raise RetryableResultEventError(f"task {event.task_id} not yet visible")
            return

        if task.status in {"succeeded", "failed"}:
            return

        instance = self.instance_repo.get_for_update(task.instance_id)
        if not instance:
            raise NotFoundError(f"instance {task.instance_id} not found")

        if event.status == "running":
            self.task_repo.mark_running(task.id, max(event.attempt_count, 1))
            return

        if event.status == "succeeded":
            self._handle_success(task.command, task.request_payload, instance.id, event)
            self.task_repo.mark_terminal(
                task.id,
                status="succeeded",
                attempt_count=max(event.attempt_count, 1),
                result_payload=event.result,
                error_code=None,
                error_message=None,
            )
            return

        self._handle_failed(task.command, task.request_payload, instance.id)
        self.task_repo.mark_terminal(
            task.id,
            status="failed",
            attempt_count=max(event.attempt_count, 1),
            result_payload=event.result,
            error_code=event.error_code,
            error_message=event.error_message,
        )

    def _handle_success(self, command: str, request_payload: dict, instance_id: UUID, event: VmResultEvent) -> None:
        if command == "create":
            ip_address = (event.result or {}).get("ip_address")
            self.instance_repo.update_state(
                instance_id,
                status="running",
                reserve_resources=True,
                last_task_id=event.task_id,
                deleted_at=None,
                ip_address=ip_address,
            )
            return

        if command == "update":
            ip_address = (event.result or {}).get("ip_address") or request_payload.get("previous_ip_address")
            self.instance_repo.update_state(
                instance_id,
                status="running",
                reserve_resources=True,
                last_task_id=event.task_id,
                deleted_at=None,
                ip_address=ip_address,
            )
            return

        if command == "delete":
            self.instance_repo.update_state(
                instance_id,
                status="deleted",
                reserve_resources=False,
                last_task_id=event.task_id,
                deleted_at=datetime.now(timezone.utc),
                ip_address=None,
            )

    def _handle_failed(self, command: str, request_payload: dict, instance_id: UUID) -> None:
        if command == "create":
            self.instance_repo.update_state(
                instance_id,
                status="error",
                reserve_resources=False,
                last_task_id=None,
                deleted_at=None,
                ip_address=None,
            )
            return

        if command == "update":
            previous_spec = request_payload.get("previous_spec", {})
            spec = ResourceSpec(
                cpu=int(previous_spec.get("cpu", 1)),
                memory_mib=int(previous_spec.get("memory_mib", 512)),
                disk_gib=int(previous_spec.get("disk_gib", 10)),
            )
            self.instance_repo.update_spec(
                instance_id,
                spec=spec,
                status="error",
                ip_address=request_payload.get("previous_ip_address"),
                reserve_resources=True,
                last_task_id=None,
                deleted_at=request_payload.get("previous_deleted_at"),
            )
            return

        if command == "delete":
            previous_spec = request_payload.get("previous_spec", {})
            spec = ResourceSpec(
                cpu=int(previous_spec.get("cpu", 1)),
                memory_mib=int(previous_spec.get("memory_mib", 512)),
                disk_gib=int(previous_spec.get("disk_gib", 10)),
            )
            self.instance_repo.update_spec(
                instance_id,
                spec=spec,
                status="error",
                ip_address=request_payload.get("previous_ip_address"),
                reserve_resources=True,
                last_task_id=None,
                deleted_at=None,
            )
