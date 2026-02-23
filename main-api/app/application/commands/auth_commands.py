from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from app.application.services.audit_logger import AuditLogger
from app.config import Settings
from app.domain.auth import User
from app.ports import (
    RefreshTokenRepository,
    TenantRepository,
    UnitOfWork,
    UserRepository,
)
from app.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
    verify_password,
)


class AuthCommandError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(frozen=True)
class LoginCommand:
    username: str
    password: str


@dataclass(frozen=True)
class RefreshTokenCommand:
    refresh_token: str


@dataclass(frozen=True)
class LogoutCommand:
    refresh_token: str
    current_user: User


class _AuthCommandSupport:
    def __init__(
        self,
        settings: Settings,
        user_repository: UserRepository,
        tenant_repository: TenantRepository,
        refresh_token_repository: RefreshTokenRepository,
        audit_logger: AuditLogger,
        uow: UnitOfWork,
    ):
        self.settings = settings
        self.user_repository = user_repository
        self.tenant_repository = tenant_repository
        self.refresh_token_repository = refresh_token_repository
        self.audit_logger = audit_logger
        self.uow = uow

    async def _issue_tokens(self, user: User) -> IssuedTokens:
        access_token, access_expires_at = create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            secret=self.settings.auth_jwt_secret,
            algorithm=self.settings.auth_jwt_algorithm,
            expire_minutes=self.settings.auth_access_token_expire_minutes,
        )
        refresh_token, refresh_expires_at = create_refresh_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            secret=self.settings.auth_jwt_secret,
            algorithm=self.settings.auth_jwt_algorithm,
            expire_days=self.settings.auth_refresh_token_expire_days,
        )
        await self.refresh_token_repository.create(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=refresh_expires_at,
        )
        return IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=access_expires_at,
        )

    async def _ensure_login_allowed(self, user: User) -> None:
        if user.role == "admin":
            return
        if user.tenant_id is None:
            raise AuthCommandError(403, "tenant is inactive")
        tenant = await self.tenant_repository.get(user.tenant_id)
        if not tenant or not tenant.is_active:
            raise AuthCommandError(403, "tenant is inactive")


class LoginHandler(_AuthCommandSupport):
    async def handle(self, command: LoginCommand) -> IssuedTokens:
        user = await self.user_repository.get_by_username(command.username)
        if not user or not verify_password(command.password, user.password_hash):
            await self.audit_logger.write(
                action="auth.login.failed",
                target_type="user",
                target_id=command.username,
                actor_username=command.username,
                metadata={"reason": "invalid_credentials"},
            )
            await self.uow.commit()
            raise AuthCommandError(401, "invalid credentials")
        if not user.is_active:
            await self.audit_logger.write(
                action="auth.login.failed",
                target_type="user",
                target_id=str(user.id),
                actor_user=user,
                metadata={"reason": "inactive_user"},
            )
            await self.uow.commit()
            raise AuthCommandError(403, "inactive user")
        await self._ensure_login_allowed(user)
        tokens = await self._issue_tokens(user)
        await self.audit_logger.write(
            action="auth.login.succeeded",
            target_type="user",
            target_id=str(user.id),
            actor_user=user,
        )
        await self.uow.commit()
        return tokens


class RefreshTokenHandler(_AuthCommandSupport):
    async def handle(self, command: RefreshTokenCommand) -> IssuedTokens:
        token_hash = hash_token(command.refresh_token)
        try:
            payload = decode_refresh_token(
                token=command.refresh_token,
                secret=self.settings.auth_jwt_secret,
                algorithms=[self.settings.auth_jwt_algorithm],
            )
        except InvalidTokenError:
            await self.audit_logger.write(
                action="auth.refresh.failed",
                target_type="refresh_token",
                target_id=None,
                metadata={"reason": "invalid_refresh_token"},
            )
            await self.uow.commit()
            raise AuthCommandError(401, "invalid refresh token")
        token_row = await self.refresh_token_repository.get_active_by_hash(token_hash)
        if not token_row:
            await self.audit_logger.write(
                action="auth.refresh.failed",
                target_type="refresh_token",
                target_id=None,
                metadata={"reason": "refresh_token_not_found_or_revoked"},
            )
            await self.uow.commit()
            raise AuthCommandError(401, "invalid refresh token")
        user = await self.user_repository.get_by_id(token_row.user_id)
        if not user or not user.is_active:
            await self.audit_logger.write(
                action="auth.refresh.failed",
                target_type="user",
                target_id=str(token_row.user_id),
                metadata={"reason": "user_not_active"},
            )
            await self.uow.commit()
            raise AuthCommandError(401, "invalid refresh token")
        await self._ensure_login_allowed(user)
        if str(user.id) != str(payload.get("sub")):
            await self.audit_logger.write(
                action="auth.refresh.failed",
                target_type="refresh_token",
                target_id=None,
                actor_user=user,
                metadata={"reason": "subject_mismatch"},
            )
            await self.uow.commit()
            raise AuthCommandError(401, "invalid refresh token")
        await self.refresh_token_repository.revoke_by_hash(token_hash)
        tokens = await self._issue_tokens(user)
        await self.audit_logger.write(
            action="auth.refresh.succeeded",
            target_type="user",
            target_id=str(user.id),
            actor_user=user,
        )
        await self.uow.commit()
        return tokens


class LogoutHandler(_AuthCommandSupport):
    async def handle(self, command: LogoutCommand) -> None:
        token_hash = hash_token(command.refresh_token)
        token_row = await self.refresh_token_repository.get_active_by_hash(token_hash)
        if token_row and token_row.user_id == command.current_user.id:
            await self.refresh_token_repository.revoke_by_hash(token_hash)
        await self.audit_logger.write(
            action="auth.logout.succeeded",
            target_type="user",
            target_id=str(command.current_user.id),
            actor_user=command.current_user,
        )
        await self.uow.commit()
