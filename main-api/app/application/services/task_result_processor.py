from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID
from app.application.services.task_instance_state import (
    revert_instance_state_on_terminal_failure,
)
from app.domain.errors import NotFoundError
from app.ports import InstanceRepository, TaskRepository


class RetryableResultEventError(Exception):
    pass


class NonRetryableResultEventError(Exception):
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

    async def process(self, event: VmResultEvent) -> None:
        if event.status not in {"running", "succeeded", "failed", "canceled"}:
            raise NonRetryableResultEventError(
                f"unsupported task result status: {event.status}"
            )
        task = await self.task_repo.get_for_update(event.task_id)
        if not task:
            now = datetime.now(timezone.utc)
            if (now - event.timestamp).total_seconds() < 60:
                raise RetryableResultEventError(f"task {event.task_id} not yet visible")
            return
        if task.status in {"succeeded", "failed", "canceled"}:
            return
        instance = await self.instance_repo.get_for_update(task.instance_id)
        if not instance:
            raise NotFoundError(f"instance {task.instance_id} not found")
        if event.status == "running":
            if task.status != "cancel_pending":
                await self.task_repo.mark_running(task.id, max(event.attempt_count, 1))
            return
        if event.status == "succeeded":
            await self._handle_success(
                task.command, task.request_payload, instance.id, event
            )
            await self.task_repo.mark_terminal(
                task.id,
                status="succeeded",
                attempt_count=max(event.attempt_count, 1),
                result_payload=event.result,
                error_code=None,
                error_message=None,
            )
            return
        if event.status == "canceled":
            await revert_instance_state_on_terminal_failure(
                instance_repo=self.instance_repo,
                instance_id=instance.id,
                command=task.command,
                request_payload=task.request_payload,
            )
            await self.task_repo.mark_canceled(
                task.id,
                attempt_count=max(event.attempt_count, task.attempt_count),
                canceled_by=None,
                cancel_reason=None,
                result_payload=event.result,
                error_code=event.error_code or "CANCELED",
                error_message=event.error_message or "task canceled",
            )
            return
        await revert_instance_state_on_terminal_failure(
            instance_repo=self.instance_repo,
            instance_id=instance.id,
            command=task.command,
            request_payload=task.request_payload,
        )
        await self.task_repo.mark_terminal(
            task.id,
            status="failed",
            attempt_count=max(event.attempt_count, 1),
            result_payload=event.result,
            error_code=event.error_code,
            error_message=event.error_message,
        )

    async def _handle_success(
        self,
        command: str,
        request_payload: dict,
        instance_id: UUID,
        event: VmResultEvent,
    ) -> None:
        if command == "create":
            ip_address = (event.result or {}).get("ip_address")
            await self.instance_repo.update_state(
                instance_id,
                status="running",
                reserve_resources=True,
                last_task_id=event.task_id,
                deleted_at=None,
                ip_address=ip_address,
            )
            return
        if command == "update":
            result = event.result or {}
            final_status = result.get("status") or "running"
            ip_address = result.get("ip_address") or request_payload.get(
                "previous_ip_address"
            )
            await self.instance_repo.update_state(
                instance_id,
                status=final_status,
                reserve_resources=True,
                last_task_id=event.task_id,
                deleted_at=None,
                ip_address=ip_address,
            )
            return
        if command == "start":
            await self.instance_repo.update_state(
                instance_id,
                status="running",
                reserve_resources=True,
                last_task_id=event.task_id,
                deleted_at=None,
                ip_address=(event.result or {}).get("ip_address")
                or request_payload.get("previous_ip_address"),
            )
            return
        if command == "stop":
            await self.instance_repo.update_state(
                instance_id,
                status="stopped",
                reserve_resources=True,
                last_task_id=event.task_id,
                deleted_at=None,
                ip_address=(event.result or {}).get("ip_address")
                or request_payload.get("previous_ip_address"),
            )
            return
        if command == "delete":
            await self.instance_repo.update_state(
                instance_id,
                status="deleted",
                reserve_resources=False,
                last_task_id=event.task_id,
                deleted_at=datetime.now(timezone.utc),
                ip_address=None,
            )
