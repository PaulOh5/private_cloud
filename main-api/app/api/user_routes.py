from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.adapters.postgres import PostgresRefreshTokenRepository, PostgresUserRepository
from app.api.audit import write_audit_log
from app.api.dependencies import get_current_user, get_session, require_roles
from app.api.schemas import (
    CreateUserRequest,
    ListRolesResponse,
    ListUsersResponse,
    RoleResponse,
    UpdateUserRequest,
    UserResponse,
)
from app.domain.auth import Role, User
from app.domain.errors import ConflictError
from app.security import hash_password

user_router = APIRouter(prefix="/users", tags=["users"])
role_router = APIRouter(prefix="/roles", tags=["roles"])


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@role_router.get("", response_model=ListRolesResponse)
def list_roles(_: User = Depends(require_roles("admin"))):
    return ListRolesResponse(items=[RoleResponse(name="admin"), RoleResponse(name="operator"), RoleResponse(name="viewer")])


@user_router.get("", response_model=ListUsersResponse)
def list_users(
    session: Session = Depends(get_session),
    _current_user: User = Depends(require_roles("admin")),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    role: str | None = Query(default=None, pattern="^(admin|operator|viewer)$"),
    is_active: bool | None = Query(default=None),
    username: str | None = Query(default=None),
):
    repo = PostgresUserRepository(session)
    items, total = repo.list_users(
        limit=limit,
        offset=offset,
        role=cast(Role | None, role),
        is_active=is_active,
        username=username,
    )
    return ListUsersResponse(
        items=[_to_user_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@user_router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: UUID, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    repo = PostgresUserRepository(session)
    user = repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return _to_user_response(user)


@user_router.post("", response_model=UserResponse, status_code=201)
def create_user(
    body: CreateUserRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("admin")),
):
    repo = PostgresUserRepository(session)
    try:
        user = repo.create_user(
            username=body.username,
            password_hash=hash_password(body.password),
            role=cast(Role, body.role),
            is_active=body.is_active,
        )
    except ConflictError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already exists")
    write_audit_log(
        session=session,
        request=request,
        action="user.create",
        target_type="user",
        target_id=str(user.id),
        actor_user=current_user,
        metadata={"role": user.role, "is_active": user.is_active},
    )
    session.commit()
    return _to_user_response(user)


@user_router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("admin")),
):
    user_repo = PostgresUserRepository(session)
    refresh_repo = PostgresRefreshTokenRepository(session)

    target = user_repo.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    new_role = cast(Role, body.role) if body.role is not None else target.role
    new_is_active = body.is_active if body.is_active is not None else target.is_active

    if current_user.id == target.id and new_is_active is False:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cannot deactivate yourself")

    if target.role == "admin" and target.is_active and (new_role != "admin" or new_is_active is False):
        if user_repo.count_active_admins() <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="at least one active admin is required")

    password_hash = hash_password(body.password) if body.password else None
    updated = user_repo.update_user(
        user_id=user_id,
        role=cast(Role | None, body.role),
        is_active=body.is_active,
        password_hash=password_hash,
    )

    if body.role is not None or body.is_active is False or body.password is not None:
        refresh_repo.revoke_all_for_user(user_id)

    write_audit_log(
        session=session,
        request=request,
        action="user.update",
        target_type="user",
        target_id=str(updated.id),
        actor_user=current_user,
        metadata={
            "role": updated.role,
            "is_active": updated.is_active,
            "password_changed": body.password is not None,
        },
    )
    session.commit()
    return _to_user_response(updated)


@user_router.delete("/{user_id}", status_code=204)
def deactivate_user(
    user_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_roles("admin")),
):
    user_repo = PostgresUserRepository(session)
    refresh_repo = PostgresRefreshTokenRepository(session)

    target = user_repo.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    if current_user.id == target.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cannot deactivate yourself")

    if target.is_active and target.role == "admin" and user_repo.count_active_admins() <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="at least one active admin is required")

    if target.is_active:
        user_repo.update_user(user_id=user_id, is_active=False)
        refresh_repo.revoke_all_for_user(user_id)
        write_audit_log(
            session=session,
            request=request,
            action="user.deactivate",
            target_type="user",
            target_id=str(user_id),
            actor_user=current_user,
        )
    session.commit()
    return Response(status_code=204)
