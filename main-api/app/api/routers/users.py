from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.adapters.postgres_repositories import PostgresRefreshTokenRepository, PostgresUserRepository
from app.api.dependencies import get_current_user, get_session, get_uow, require_roles
from app.api.schemas import (
    CreateUserRequest,
    ListRolesResponse,
    ListUsersResponse,
    RoleResponse,
    UpdateUserRequest,
    UserResponse,
)
from app.application.commands.user_commands import (
    CreateUserCommand,
    CreateUserHandler,
    DeactivateUserCommand,
    DeactivateUserHandler,
    UpdateUserCommand,
    UpdateUserHandler,
)
from app.application.queries.get_user import GetUserHandler
from app.application.queries.list_roles import ListRolesHandler
from app.application.queries.list_users import ListUsersHandler, ListUsersQuery
from app.application.services.audit_logger import AuditLogger
from app.domain.auth import User
from app.domain.errors import ConflictError, UserNotFoundError
from app.infra.uow import SqlAlchemyUnitOfWork

user_router = APIRouter(prefix="/users", tags=["users"])
role_router = APIRouter(prefix="/roles", tags=["roles"])


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        tenant_id=user.tenant_id,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _raise_conflict_as_http(exc: ConflictError) -> None:
    message = str(exc)
    if message in {
        "admin user must not have tenant_id",
        "tenant_id is required for non-admin user",
    }:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc


@role_router.get("", response_model=ListRolesResponse)
def list_roles(
    _: User = Depends(require_roles("admin")),
    _session: Session = Depends(get_session),
    _uow: SqlAlchemyUnitOfWork = Depends(get_uow),
):
    handler = ListRolesHandler()
    return ListRolesResponse(items=[RoleResponse(name=name) for name in handler.handle()])


@user_router.get("", response_model=ListUsersResponse)
def list_users(
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    _current_user: User = Depends(require_roles("admin")),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    role: str | None = Query(default=None, pattern="^(admin|operator|viewer)$"),
    is_active: bool | None = Query(default=None),
    username: str | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
):
    handler = ListUsersHandler(user_repository=PostgresUserRepository(session))
    result = handler.handle(
        ListUsersQuery(
            limit=limit,
            offset=offset,
            role=role,
            is_active=is_active,
            username=username,
            tenant_id=tenant_id,
        )
    )
    return ListUsersResponse(
        items=[_to_user_response(item) for item in result.items],
        total=result.total,
        limit=limit,
        offset=offset,
    )


@user_router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: UUID,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    use_cases = GetUserHandler(user_repository=PostgresUserRepository(session))
    try:
        user = use_cases.handle(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found") from exc
    return _to_user_response(user)


@user_router.post("", response_model=UserResponse, status_code=201)
def create_user(
    body: CreateUserRequest,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("admin")),
):
    handler = CreateUserHandler(
        user_repository=PostgresUserRepository(session),
        refresh_token_repository=PostgresRefreshTokenRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        user = handler.handle(
            CreateUserCommand(
                username=body.username,
                password=body.password,
                role=body.role,
                tenant_id=body.tenant_id,
                is_active=body.is_active,
                actor=current_user,
            )
        )
    except ConflictError as exc:
        _raise_conflict_as_http(exc)
    return _to_user_response(user)


@user_router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("admin")),
):
    handler = UpdateUserHandler(
        user_repository=PostgresUserRepository(session),
        refresh_token_repository=PostgresRefreshTokenRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        updated = handler.handle(
            UpdateUserCommand(
                user_id=user_id,
                role=body.role,
                tenant_id=body.tenant_id,
                is_active=body.is_active,
                password=body.password,
                actor=current_user,
            )
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found") from exc
    except ConflictError as exc:
        _raise_conflict_as_http(exc)
    return _to_user_response(updated)


@user_router.delete("/{user_id}", status_code=204)
def deactivate_user(
    user_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
    current_user: User = Depends(require_roles("admin")),
):
    handler = DeactivateUserHandler(
        user_repository=PostgresUserRepository(session),
        refresh_token_repository=PostgresRefreshTokenRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        handler.handle(DeactivateUserCommand(user_id=user_id, actor=current_user))
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found") from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=204)
