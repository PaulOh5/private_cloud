from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.adapters.postgres import PostgresRefreshTokenRepository, PostgresTenantRepository, PostgresUserRepository
from app.api.audit import write_audit_log
from app.api.dependencies import get_current_user, get_session
from app.api.schemas import AccessTokenResponse, CurrentUserResponse, LoginRequest, RefreshTokenRequest
from app.domain.auth import User
from app.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
    verify_password,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(request: Request, user: User, session: Session) -> AccessTokenResponse:
    settings = request.app.state.settings
    refresh_repo = PostgresRefreshTokenRepository(session)
    access_token, access_expires_at = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        secret=settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
        expire_minutes=settings.auth_access_token_expire_minutes,
    )
    refresh_token, refresh_expires_at = create_refresh_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        secret=settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
        expire_days=settings.auth_refresh_token_expire_days,
    )
    refresh_repo.create(user_id=user.id, token_hash=hash_token(refresh_token), expires_at=refresh_expires_at)
    return AccessTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=access_expires_at,
    )


def _ensure_login_allowed(user: User, session: Session) -> None:
    if user.role == "admin":
        return
    if user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant is inactive")
    tenant = PostgresTenantRepository(session).get(user.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant is inactive")


@auth_router.post("/login", response_model=AccessTokenResponse)
def login(body: LoginRequest, request: Request, session: Session = Depends(get_session)):
    user_repo = PostgresUserRepository(session)
    user = user_repo.get_by_username(body.username)
    if not user or not verify_password(body.password, user.password_hash):
        write_audit_log(
            session=session,
            request=request,
            action="auth.login.failed",
            target_type="user",
            target_id=body.username,
            actor_username=body.username,
            metadata={"reason": "invalid_credentials"},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    if not user.is_active:
        write_audit_log(
            session=session,
            request=request,
            action="auth.login.failed",
            target_type="user",
            target_id=str(user.id),
            actor_user=user,
            metadata={"reason": "inactive_user"},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="inactive user")
    _ensure_login_allowed(user, session)

    response = _issue_tokens(request, user, session)
    write_audit_log(
        session=session,
        request=request,
        action="auth.login.succeeded",
        target_type="user",
        target_id=str(user.id),
        actor_user=user,
    )
    session.commit()
    return response


@auth_router.post("/refresh", response_model=AccessTokenResponse)
def refresh_token(body: RefreshTokenRequest, request: Request, session: Session = Depends(get_session)):
    settings = request.app.state.settings
    token_hash = hash_token(body.refresh_token)
    refresh_repo = PostgresRefreshTokenRepository(session)
    user_repo = PostgresUserRepository(session)

    try:
        payload = decode_refresh_token(
            token=body.refresh_token,
            secret=settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
        )
    except InvalidTokenError:
        write_audit_log(
            session=session,
            request=request,
            action="auth.refresh.failed",
            target_type="refresh_token",
            target_id=None,
            metadata={"reason": "invalid_refresh_token"},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")

    token_row = refresh_repo.get_active_by_hash(token_hash)
    if not token_row:
        write_audit_log(
            session=session,
            request=request,
            action="auth.refresh.failed",
            target_type="refresh_token",
            target_id=None,
            metadata={"reason": "refresh_token_not_found_or_revoked"},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")

    user = user_repo.get_by_id(token_row.user_id)
    if not user or not user.is_active:
        write_audit_log(
            session=session,
            request=request,
            action="auth.refresh.failed",
            target_type="user",
            target_id=str(token_row.user_id),
            metadata={"reason": "user_not_active"},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")
    _ensure_login_allowed(user, session)
    if str(user.id) != str(payload.get("sub")):
        write_audit_log(
            session=session,
            request=request,
            action="auth.refresh.failed",
            target_type="refresh_token",
            target_id=None,
            actor_user=user,
            metadata={"reason": "subject_mismatch"},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")

    refresh_repo.revoke_by_hash(token_hash)
    response = _issue_tokens(request, user, session)
    write_audit_log(
        session=session,
        request=request,
        action="auth.refresh.succeeded",
        target_type="user",
        target_id=str(user.id),
        actor_user=user,
    )
    session.commit()
    return response


@auth_router.post("/logout", status_code=204)
def logout(
    body: RefreshTokenRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token_hash = hash_token(body.refresh_token)
    refresh_repo = PostgresRefreshTokenRepository(session)
    token_row = refresh_repo.get_active_by_hash(token_hash)
    if token_row and token_row.user_id == current_user.id:
        refresh_repo.revoke_by_hash(token_hash)
    write_audit_log(
        session=session,
        request=request,
        action="auth.logout.succeeded",
        target_type="user",
        target_id=str(current_user.id),
        actor_user=current_user,
    )
    session.commit()
    return Response(status_code=204)


@auth_router.get("/me", response_model=CurrentUserResponse)
def me(current_user: User = Depends(get_current_user)):
    return CurrentUserResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        tenant_id=current_user.tenant_id,
        is_active=current_user.is_active,
    )
