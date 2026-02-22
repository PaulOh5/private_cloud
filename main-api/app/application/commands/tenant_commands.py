from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.application.services.audit_logger import AuditLogger
from app.domain.auth import User
from app.domain.errors import ConflictError, QuotaConflictError, TenantNotFoundError
from app.ports import TenantQuotaRepository, TenantRepository, TenantUsageReadPort, UnitOfWork

DEFAULT_TENANT_KEY = "default"


@dataclass(frozen=True)
class CreateTenantCommand:
    key: str
    name: str
    is_active: bool
    max_instances: int
    max_cpu: int
    max_memory_mib: int
    max_disk_gib: int
    actor: User


@dataclass(frozen=True)
class UpdateTenantCommand:
    tenant_id: UUID
    name: str | None
    is_active: bool | None
    actor: User


@dataclass(frozen=True)
class UpdateTenantQuotaCommand:
    tenant_id: UUID
    max_instances: int
    max_cpu: int
    max_memory_mib: int
    max_disk_gib: int
    actor: User


@dataclass(frozen=True)
class DeleteTenantCommand:
    tenant_id: UUID
    actor: User


class CreateTenantHandler:
    def __init__(
        self,
        tenant_repository: TenantRepository,
        tenant_quota_repository: TenantQuotaRepository,
        audit_logger: AuditLogger,
        uow: UnitOfWork,
    ):
        self.tenant_repository = tenant_repository
        self.tenant_quota_repository = tenant_quota_repository
        self.audit_logger = audit_logger
        self.uow = uow

    def handle(self, command: CreateTenantCommand):
        try:
            tenant = self.tenant_repository.create(
                key=command.key,
                name=command.name,
                is_active=command.is_active,
            )
        except ConflictError:
            raise ConflictError("tenant key already exists")

        quota = self.tenant_quota_repository.upsert(
            tenant.id,
            max_instances=command.max_instances,
            max_cpu=command.max_cpu,
            max_memory_mib=command.max_memory_mib,
            max_disk_gib=command.max_disk_gib,
        )

        self.audit_logger.write(
            action="tenant.create",
            target_type="tenant",
            target_id=str(tenant.id),
            actor_user=command.actor,
            tenant_id=tenant.id,
            metadata={
                "key": tenant.key,
                "max_instances": quota.max_instances,
                "max_cpu": quota.max_cpu,
                "max_memory_mib": quota.max_memory_mib,
                "max_disk_gib": quota.max_disk_gib,
            },
        )
        self.uow.commit()
        return tenant, quota


class UpdateTenantHandler:
    def __init__(
        self,
        tenant_repository: TenantRepository,
        tenant_quota_repository: TenantQuotaRepository,
        audit_logger: AuditLogger,
        uow: UnitOfWork,
    ):
        self.tenant_repository = tenant_repository
        self.tenant_quota_repository = tenant_quota_repository
        self.audit_logger = audit_logger
        self.uow = uow

    def handle(self, command: UpdateTenantCommand):
        tenant = self.tenant_repository.get(command.tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"tenant {command.tenant_id} not found")
        if tenant.key == DEFAULT_TENANT_KEY and command.is_active is False:
            raise ConflictError("default tenant cannot be deactivated")

        updated = self.tenant_repository.update(
            command.tenant_id,
            name=command.name,
            is_active=command.is_active,
        )
        self.audit_logger.write(
            action="tenant.update",
            target_type="tenant",
            target_id=str(updated.id),
            actor_user=command.actor,
            tenant_id=updated.id,
            metadata={"name": updated.name, "is_active": updated.is_active},
        )
        self.uow.commit()
        return updated, self.tenant_quota_repository.get(updated.id)


class UpdateTenantQuotaHandler:
    def __init__(
        self,
        tenant_repository: TenantRepository,
        tenant_quota_repository: TenantQuotaRepository,
        tenant_usage_read_port: TenantUsageReadPort,
        audit_logger: AuditLogger,
        uow: UnitOfWork,
    ):
        self.tenant_repository = tenant_repository
        self.tenant_quota_repository = tenant_quota_repository
        self.tenant_usage_read_port = tenant_usage_read_port
        self.audit_logger = audit_logger
        self.uow = uow

    def handle(self, command: UpdateTenantQuotaCommand):
        tenant = self.tenant_repository.get(command.tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"tenant {command.tenant_id} not found")

        usage = self.tenant_usage_read_port.get_usage(command.tenant_id)
        if command.max_instances < usage.used_instances:
            raise QuotaConflictError("max_instances cannot be lower than current usage")
        if command.max_cpu < usage.used_cpu:
            raise QuotaConflictError("max_cpu cannot be lower than current usage")
        if command.max_memory_mib < usage.used_memory_mib:
            raise QuotaConflictError("max_memory_mib cannot be lower than current usage")
        if command.max_disk_gib < usage.used_disk_gib:
            raise QuotaConflictError("max_disk_gib cannot be lower than current usage")

        updated = self.tenant_quota_repository.upsert(
            command.tenant_id,
            max_instances=command.max_instances,
            max_cpu=command.max_cpu,
            max_memory_mib=command.max_memory_mib,
            max_disk_gib=command.max_disk_gib,
        )
        self.audit_logger.write(
            action="tenant.quota.update",
            target_type="tenant",
            target_id=str(command.tenant_id),
            actor_user=command.actor,
            tenant_id=command.tenant_id,
            metadata={
                "max_instances": updated.max_instances,
                "max_cpu": updated.max_cpu,
                "max_memory_mib": updated.max_memory_mib,
                "max_disk_gib": updated.max_disk_gib,
            },
        )
        self.uow.commit()
        return updated


class DeleteTenantHandler:
    def __init__(
        self,
        tenant_repository: TenantRepository,
        audit_logger: AuditLogger,
        uow: UnitOfWork,
    ):
        self.tenant_repository = tenant_repository
        self.audit_logger = audit_logger
        self.uow = uow

    def handle(self, command: DeleteTenantCommand) -> None:
        tenant = self.tenant_repository.get(command.tenant_id)
        if not tenant:
            raise TenantNotFoundError(f"tenant {command.tenant_id} not found")
        if tenant.key == DEFAULT_TENANT_KEY:
            raise ConflictError("default tenant cannot be deleted")
        if self.tenant_repository.count_active_users(command.tenant_id) > 0:
            raise ConflictError("tenant has active users")
        if self.tenant_repository.count_active_instances(command.tenant_id) > 0:
            raise ConflictError("tenant has active instances")

        self.tenant_repository.delete(command.tenant_id)
        self.audit_logger.write(
            action="tenant.delete",
            target_type="tenant",
            target_id=str(command.tenant_id),
            actor_user=command.actor,
            tenant_id=command.tenant_id,
        )
        self.uow.commit()
