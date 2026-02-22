from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from app.application.services.audit_logger import AuditLogger
from app.domain.auth import Role, User
from app.domain.errors import ConflictError, UserNotFoundError
from app.ports import RefreshTokenRepository, UnitOfWork, UserRepository
from app.security import hash_password


@dataclass(frozen=True)
class CreateUserCommand:
    username: str
    password: str
    role: str
    tenant_id: UUID | None
    is_active: bool
    actor: User


@dataclass(frozen=True)
class UpdateUserCommand:
    user_id: UUID
    role: str | None
    tenant_id: UUID | None
    is_active: bool | None
    password: str | None
    actor: User


@dataclass(frozen=True)
class DeactivateUserCommand:
    user_id: UUID
    actor: User


class CreateUserHandler:
    def __init__(
        self,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        audit_logger: AuditLogger,
        uow: UnitOfWork,
    ):
        self.user_repository = user_repository
        self.refresh_token_repository = refresh_token_repository
        self.audit_logger = audit_logger
        self.uow = uow

    def handle(self, command: CreateUserCommand) -> User:
        role_value = cast(Role, command.role)
        if role_value == "admin" and command.tenant_id is not None:
            raise ConflictError("admin user must not have tenant_id")
        if role_value in {"operator", "viewer"} and command.tenant_id is None:
            raise ConflictError("tenant_id is required for non-admin user")

        try:
            user = self.user_repository.create_user(
                username=command.username,
                password_hash=hash_password(command.password),
                role=role_value,
                is_active=command.is_active,
                tenant_id=command.tenant_id,
            )
        except ConflictError:
            raise ConflictError("username already exists")

        self.audit_logger.write(
            action="user.create",
            target_type="user",
            target_id=str(user.id),
            actor_user=command.actor,
            tenant_id=user.tenant_id,
            metadata={"role": user.role, "is_active": user.is_active},
        )
        self.uow.commit()
        return user


class UpdateUserHandler:
    def __init__(
        self,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        audit_logger: AuditLogger,
        uow: UnitOfWork,
    ):
        self.user_repository = user_repository
        self.refresh_token_repository = refresh_token_repository
        self.audit_logger = audit_logger
        self.uow = uow

    def handle(self, command: UpdateUserCommand) -> User:
        target = self.user_repository.get_by_id(command.user_id)
        if not target:
            raise UserNotFoundError(f"user {command.user_id} not found")

        new_role = cast(Role, command.role) if command.role is not None else target.role
        new_is_active = command.is_active if command.is_active is not None else target.is_active
        new_tenant_id = command.tenant_id if command.tenant_id is not None else target.tenant_id

        if new_role == "admin":
            if command.tenant_id is not None:
                raise ConflictError("admin user must not have tenant_id")
            new_tenant_id = None
        elif new_tenant_id is None:
            raise ConflictError("tenant_id is required for non-admin user")

        if command.actor.id == target.id and new_is_active is False:
            raise ConflictError("cannot deactivate yourself")

        if target.role == "admin" and target.is_active and (new_role != "admin" or new_is_active is False):
            if self.user_repository.count_active_admins() <= 1:
                raise ConflictError("at least one active admin is required")

        password_hash = hash_password(command.password) if command.password else None
        updated = self.user_repository.update_user(
            user_id=command.user_id,
            role=cast(Role | None, command.role),
            is_active=command.is_active,
            password_hash=password_hash,
            tenant_id=new_tenant_id,
        )

        if command.role is not None or command.is_active is False or command.password is not None:
            self.refresh_token_repository.revoke_all_for_user(command.user_id)

        self.audit_logger.write(
            action="user.update",
            target_type="user",
            target_id=str(updated.id),
            actor_user=command.actor,
            tenant_id=updated.tenant_id,
            metadata={
                "role": updated.role,
                "is_active": updated.is_active,
                "password_changed": command.password is not None,
            },
        )
        self.uow.commit()
        return updated


class DeactivateUserHandler:
    def __init__(
        self,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        audit_logger: AuditLogger,
        uow: UnitOfWork,
    ):
        self.user_repository = user_repository
        self.refresh_token_repository = refresh_token_repository
        self.audit_logger = audit_logger
        self.uow = uow

    def handle(self, command: DeactivateUserCommand) -> None:
        target = self.user_repository.get_by_id(command.user_id)
        if not target:
            raise UserNotFoundError(f"user {command.user_id} not found")

        if command.actor.id == target.id:
            raise ConflictError("cannot deactivate yourself")

        if target.is_active and target.role == "admin" and self.user_repository.count_active_admins() <= 1:
            raise ConflictError("at least one active admin is required")

        if target.is_active:
            self.user_repository.update_user(user_id=command.user_id, is_active=False)
            self.refresh_token_repository.revoke_all_for_user(command.user_id)
            self.audit_logger.write(
                action="user.deactivate",
                target_type="user",
                target_id=str(command.user_id),
                actor_user=command.actor,
                tenant_id=target.tenant_id,
            )
        self.uow.commit()
