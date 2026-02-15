from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.postgres import PostgresInstanceReadRepository, PostgresInstanceRepository, PostgresUserRepository
from app.adapters.rabbitmq_rpc import RabbitMqVmProvisioningAdapter
from app.adapters.resource_accounting import HostResourceAccountingAdapter
from app.domain.auth import User
from app.security import InvalidTokenError, decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_session(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def advisory_lock(session: Session, key: int = 4001) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def get_write_repo(session: Session = None):
    return PostgresInstanceRepository(session)


def get_read_repo(session: Session = None):
    return PostgresInstanceReadRepository(session)


def get_accounting(session: Session = None):
    return HostResourceAccountingAdapter(session)


def get_vm_port(request: Request) -> RabbitMqVmProvisioningAdapter:
    return request.app.state.vm_port


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
