from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.postgres_repositories import (
    PostgresRefreshTokenRepository,
    PostgresTenantRepository,
    PostgresUserRepository,
)
from app.api.dependencies import get_current_user, get_session, get_uow
from app.api.schemas import (
    AccessTokenResponse,
    CurrentUserResponse,
    LoginRequest,
    RefreshTokenRequest,
)
from app.application.services.audit_logger import AuditLogger
from app.application.commands.auth_commands import (
    AuthCommandError,
    LoginCommand,
    LoginHandler,
    LogoutCommand,
    LogoutHandler,
    RefreshTokenCommand,
    RefreshTokenHandler,
)
from app.domain.auth import User
from app.infra.uow import SqlAlchemyUnitOfWork

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/login", response_model=AccessTokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
):
    handler = LoginHandler(
        settings=request.app.state.settings,
        user_repository=PostgresUserRepository(session),
        tenant_repository=PostgresTenantRepository(session),
        refresh_token_repository=PostgresRefreshTokenRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        tokens = await handler.handle(
            LoginCommand(username=body.username, password=body.password)
        )
    except AuthCommandError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AccessTokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_at=tokens.expires_at,
    )


@auth_router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_token(
    body: RefreshTokenRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
):
    handler = RefreshTokenHandler(
        settings=request.app.state.settings,
        user_repository=PostgresUserRepository(session),
        tenant_repository=PostgresTenantRepository(session),
        refresh_token_repository=PostgresRefreshTokenRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    try:
        tokens = await handler.handle(
            RefreshTokenCommand(refresh_token=body.refresh_token)
        )
    except AuthCommandError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AccessTokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_at=tokens.expires_at,
    )


@auth_router.post("/logout", status_code=204)
async def logout(
    body: RefreshTokenRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    uow: SqlAlchemyUnitOfWork = Depends(get_uow),
):
    handler = LogoutHandler(
        settings=request.app.state.settings,
        user_repository=PostgresUserRepository(session),
        tenant_repository=PostgresTenantRepository(session),
        refresh_token_repository=PostgresRefreshTokenRepository(session),
        audit_logger=AuditLogger(session, request),
        uow=uow,
    )
    await handler.handle(
        LogoutCommand(refresh_token=body.refresh_token, current_user=current_user)
    )
    return Response(status_code=204)


@auth_router.get("/me", response_model=CurrentUserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return CurrentUserResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        tenant_id=current_user.tenant_id,
        is_active=current_user.is_active,
    )
