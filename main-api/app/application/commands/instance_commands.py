from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4
from app.application.commands.common import TaskAccepted
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.models import Instance, InstanceTask, ResourceSpec
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

    async def handle(self, command: CreateInstanceCommand) -> TaskAccepted:
        spec = ResourceSpec(
            cpu=command.cpu, memory_mib=command.memory_mib, disk_gib=command.disk_gib
        )
        spec.validate()
        if self.quota_accounting is not None:
            await self.quota_accounting.assert_quota(
                TenantQuotaCheckInput(
                    tenant_id=command.tenant_id,
                    current=None,
                    requested=spec,
                    current_profile="none",
                    requested_profile="running",
                )
            )
        await self.accounting.assert_capacity(
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
        await self.write_repository.create(instance)
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
        await self.task_repository.create_task(task)
        await self.outbox_repository.enqueue_command(
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

    async def handle(self, command: DeleteInstanceCommand) -> TaskAccepted:
        instance = await self.write_repository.get_for_update(command.instance_id)
        if not instance:
            raise NotFoundError(f"instance {command.instance_id} not found")
        if instance.status == "deleted":
            raise ValidationError("instance is already deleted")
        if await self.task_repository.has_active_task(command.instance_id):
            raise ConflictError(
                f"instance {command.instance_id} already has an active task"
            )
        task_id = uuid4()
        request_id = uuid4()
        now = datetime.now(timezone.utc)
        await self.write_repository.update_state(
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
        await self.task_repository.create_task(task)
        await self.outbox_repository.enqueue_command(
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


@dataclass(frozen=True)
class StopInstanceCommand:
    instance_id: UUID


class StopInstanceHandler:
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

    async def handle(self, command: StopInstanceCommand) -> TaskAccepted:
        instance = await self.write_repository.get_for_update(command.instance_id)
        if not instance:
            raise NotFoundError(f"instance {command.instance_id} not found")
        if instance.status == "deleted":
            raise ValidationError("cannot stop a deleted instance")
        if instance.status not in {"running", "stopped"}:
            raise ValidationError(f"cannot stop instance from status {instance.status}")
        if await self.task_repository.has_active_task(command.instance_id):
            raise ConflictError(
                f"instance {command.instance_id} already has an active task"
            )
        task_id = uuid4()
        request_id = uuid4()
        now = datetime.now(timezone.utc)
        await self.write_repository.update_state(
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
        await self.task_repository.create_task(task)
        await self.outbox_repository.enqueue_command(
            topic="instance.stop",
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
            command="stop",
            status="queued",
            accepted_at=now,
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

    async def handle(self, command: StartInstanceCommand) -> TaskAccepted:
        instance = await self.write_repository.get_for_update(command.instance_id)
        if not instance:
            raise NotFoundError(f"instance {command.instance_id} not found")
        if instance.status == "deleted":
            raise ValidationError("cannot start a deleted instance")
        if instance.status not in {"running", "stopped"}:
            raise ValidationError(
                f"cannot start instance from status {instance.status}"
            )
        if await self.task_repository.has_active_task(command.instance_id):
            raise ConflictError(
                f"instance {command.instance_id} already has an active task"
            )
        if instance.status == "stopped":
            if self.quota_accounting is not None:
                await self.quota_accounting.assert_quota(
                    TenantQuotaCheckInput(
                        tenant_id=instance.tenant_id,
                        current=instance.resource_spec,
                        requested=instance.resource_spec,
                        current_profile="stopped",
                        requested_profile="running",
                    )
                )
            await self.accounting.assert_capacity(
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
        await self.write_repository.update_state(
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
        await self.task_repository.create_task(task)
        await self.outbox_repository.enqueue_command(
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


@dataclass(frozen=True)
class UpdateInstanceCommand:
    instance_id: UUID
    cpu: int
    memory_mib: int
    disk_gib: int
    host_node: str


class UpdateInstanceHandler:
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

    async def handle(self, command: UpdateInstanceCommand) -> TaskAccepted:
        instance = await self.write_repository.get_for_update(command.instance_id)
        if not instance:
            raise NotFoundError(f"instance {command.instance_id} not found")
        if instance.status == "deleted":
            raise ValidationError("cannot update a deleted instance")
        if await self.task_repository.has_active_task(command.instance_id):
            raise ConflictError(
                f"instance {command.instance_id} already has an active task"
            )
        next_spec = ResourceSpec(
            cpu=command.cpu, memory_mib=command.memory_mib, disk_gib=command.disk_gib
        )
        next_spec.validate()
        current_profile = self._profile_for_instance(
            instance.status, instance.reserve_resources
        )
        requested_profile = "stopped" if instance.status == "stopped" else "running"
        boot_after_update = instance.status != "stopped"
        if self.quota_accounting is not None:
            await self.quota_accounting.assert_quota(
                TenantQuotaCheckInput(
                    tenant_id=instance.tenant_id,
                    current=instance.resource_spec,
                    requested=next_spec,
                    current_profile=current_profile,
                    requested_profile=requested_profile,
                )
            )
        await self.accounting.assert_capacity(
            CapacityCheckInput(
                host_node=command.host_node,
                current=instance.resource_spec,
                requested=next_spec,
                current_profile=current_profile,
                requested_profile=requested_profile,
            )
        )
        task_id = uuid4()
        request_id = uuid4()
        now = datetime.now(timezone.utc)
        await self.write_repository.update_spec(
            command.instance_id,
            spec=next_spec,
            status="updating_pending",
            ip_address=instance.ip_address,
            reserve_resources=True,
            last_task_id=task_id,
            deleted_at=instance.deleted_at,
        )
        task = InstanceTask(
            id=task_id,
            instance_id=command.instance_id,
            command="update",
            status="queued",
            request_id=request_id,
            request_payload={
                "cpu": next_spec.cpu,
                "memory_mib": next_spec.memory_mib,
                "disk_gib": next_spec.disk_gib,
                "host_node": command.host_node,
                "tenant_id": str(instance.tenant_id),
                "boot_after_update": boot_after_update,
                "previous_spec": {
                    "cpu": instance.resource_spec.cpu,
                    "memory_mib": instance.resource_spec.memory_mib,
                    "disk_gib": instance.resource_spec.disk_gib,
                },
                "previous_ip_address": instance.ip_address,
                "previous_deleted_at": instance.deleted_at.isoformat()
                if instance.deleted_at
                else None,
                "previous_status": instance.status,
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
        await self.task_repository.create_task(task)
        await self.outbox_repository.enqueue_command(
            topic="instance.update",
            payload={
                "instance_id": str(command.instance_id),
                "cpu": next_spec.cpu,
                "memory_mib": next_spec.memory_mib,
                "disk_gib": next_spec.disk_gib,
                "host_node": command.host_node,
                "boot_after_update": boot_after_update,
            },
            task_id=task_id,
            request_id=request_id,
            max_attempts=self.outbox_max_attempts,
        )
        return TaskAccepted(
            task_id=task_id,
            instance_id=command.instance_id,
            command="update",
            status="queued",
            accepted_at=now,
        )

    def _profile_for_instance(self, status: str, reserve_resources: bool) -> str:
        if not reserve_resources:
            return "none"
        if status == "stopped":
            return "stopped"
        return "running"
