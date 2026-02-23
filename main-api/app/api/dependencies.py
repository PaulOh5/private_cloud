from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.postgres_repositories import (
    PostgresCommandOutboxRepository,
    PostgresInstanceReadRepository,
    PostgresInstanceRepository,
    PostgresTaskRepository,
    PostgresTenantRepository,
    PostgresUserRepository,
)
from app.adapters.resource_accounting import (
    HostResourceAccountingAdapter,
    TenantQuotaAccountingAdapter,
)
from app.application.services.access_control import (
    ensure_instance_access as _ensure_instance_access,
    ensure_mutation_allowed_for_user_tenant as _ensure_mutation_allowed_for_user_tenant,
    ensure_task_access as _ensure_task_access,
    resolve_tenant_for_create as _resolve_tenant_for_create,
    resolve_tenant_scope_for_list as _resolve_tenant_scope_for_list,
)
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


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = getattr(
        request.app.state, "async_session_factory", request.app.state.session_factory
    )
    async with session_factory() as session:
        yield session


def get_uow(session: AsyncSession = Depends(get_session)) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session)


async def advisory_lock(session: AsyncSession, key: int = 4001) -> None:
    uow = SqlAlchemyUnitOfWork(session)
    await uow.advisory_lock(key)


def get_vm_port(request: Request) -> VmProvisioningPort:
    return request.app.state.vm_port


def build_vm_query_deps(session: AsyncSession) -> VmQueryDeps:
    return VmQueryDeps(
        read_repository=PostgresInstanceReadRepository(session),
        task_repository=PostgresTaskRepository(session),
    )


def build_vm_mutation_deps(
    session: AsyncSession, *, outbox_notify_channel: str
) -> VmMutationDeps:
    return VmMutationDeps(
        read_repository=PostgresInstanceReadRepository(session),
        write_repository=PostgresInstanceRepository(session),
        task_repository=PostgresTaskRepository(session),
        outbox_repository=PostgresCommandOutboxRepository(
            session, notify_channel=outbox_notify_channel
        ),
        accounting=HostResourceAccountingAdapter(session),
        quota_accounting=TenantQuotaAccountingAdapter(session),
    )


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )

    user = await PostgresUserRepository(session).get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )
    return user


def require_roles(*roles: str):
    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        return current_user

    return _dependency


def ensure_instance_access(current_user: User, instance_tenant_id: UUID) -> None:
    _ensure_instance_access(current_user, instance_tenant_id)


def ensure_task_access(current_user: User, task_tenant_id: UUID) -> None:
    _ensure_task_access(current_user, task_tenant_id)


def resolve_tenant_scope_for_list(
    current_user: User, requested_tenant_id: UUID | None
) -> UUID | None:
    return _resolve_tenant_scope_for_list(current_user, requested_tenant_id)


def resolve_tenant_for_create(
    current_user: User, requested_tenant_id: UUID | None
) -> UUID:
    return _resolve_tenant_for_create(current_user, requested_tenant_id)


async def ensure_mutation_allowed_for_user_tenant(
    session: AsyncSession, current_user: User
) -> None:
    await _ensure_mutation_allowed_for_user_tenant(
        PostgresTenantRepository(session), current_user
    )
