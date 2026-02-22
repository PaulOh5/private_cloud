from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.postgres_repositories import (
    PostgresCommandOutboxRepository,
    PostgresInstanceReadRepository,
    PostgresInstanceRepository,
    PostgresTaskRepository,
    PostgresUserRepository,
)
from app.adapters.resource_accounting import HostResourceAccountingAdapter, TenantQuotaAccountingAdapter
from app.domain.auth import User
from app.infra.uow import SqlAlchemyUnitOfWork
from app.ports import (
    CommandOutboxRepository,
    InstanceReadRepository,
    InstanceRepository,
    ResourceAccountingPort,
    TaskRepository,
    TenantQuotaAccountingPort,
    VmProvisioningPort,
)
from app.security import InvalidTokenError, decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass(frozen=True)
class VmQueryDeps:
    read_repository: InstanceReadRepository
    task_repository: TaskRepository


@dataclass(frozen=True)
class VmMutationDeps:
    read_repository: InstanceReadRepository
    write_repository: InstanceRepository
    task_repository: TaskRepository
    outbox_repository: CommandOutboxRepository
    accounting: ResourceAccountingPort
    quota_accounting: TenantQuotaAccountingPort


def get_session(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_uow(session: Session = Depends(get_session)) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session)


def advisory_lock(session: Session, key: int = 4001) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def get_vm_port(request: Request) -> VmProvisioningPort:
    return request.app.state.vm_port


def build_vm_query_deps(session: Session) -> VmQueryDeps:
    return VmQueryDeps(
        read_repository=PostgresInstanceReadRepository(session),
        task_repository=PostgresTaskRepository(session),
    )


def build_vm_mutation_deps(session: Session, *, outbox_notify_channel: str) -> VmMutationDeps:
    return VmMutationDeps(
        read_repository=PostgresInstanceReadRepository(session),
        write_repository=PostgresInstanceRepository(session),
        task_repository=PostgresTaskRepository(session),
        outbox_repository=PostgresCommandOutboxRepository(session, notify_channel=outbox_notify_channel),
        accounting=HostResourceAccountingAdapter(session),
        quota_accounting=TenantQuotaAccountingAdapter(session),
    )


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme),
) -> User:
    settings = request.app.state.settings
    try:
        payload = decode_access_token(
            token=token,
            secret=settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
        )
        user_id = UUID(str(payload.get("sub")))
    except (InvalidTokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    user = PostgresUserRepository(session).get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    return user


def require_roles(*roles: str):
    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return current_user

    return _dependency


def ensure_instance_access(current_user: User, instance_tenant_id: UUID) -> None:
    if current_user.role != "admin" and current_user.tenant_id != instance_tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")


def ensure_task_access(current_user: User, task_tenant_id: UUID) -> None:
    if current_user.role != "admin" and current_user.tenant_id != task_tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")


def resolve_tenant_scope_for_list(current_user: User, requested_tenant_id: UUID | None) -> UUID | None:
    if current_user.role == "admin":
        return requested_tenant_id
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope required")
    if requested_tenant_id is not None and requested_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    return current_user.tenant_id


def resolve_tenant_for_create(current_user: User, requested_tenant_id: UUID | None) -> UUID:
    if current_user.role == "admin":
        if requested_tenant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id is required for admin")
        return requested_tenant_id

    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope required")
    if requested_tenant_id is not None and requested_tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    return current_user.tenant_id


def ensure_mutation_allowed_for_user_tenant(session: Session, current_user: User) -> None:
    if current_user.role == "admin":
        return
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope required")

    row = session.execute(
        text("SELECT is_active FROM tenants WHERE id = :id"),
        {"id": str(current_user.tenant_id)},
    ).mappings().first()
    if not row or not bool(row["is_active"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant is inactive")
