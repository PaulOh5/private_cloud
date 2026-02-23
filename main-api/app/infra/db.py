from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Callable

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.infra.migrations import apply_schema as run_schema_migrations


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.postgres_async_dsn, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


class _SyncSessionProxy:
    def __init__(self, session: AsyncSession, loop: asyncio.AbstractEventLoop):
        self._session = session
        self._loop = loop

    def _run(self, coroutine):
        return self._loop.run_until_complete(coroutine)

    def execute(self, *args, **kwargs):
        return self._run(self._session.execute(*args, **kwargs))

    def scalar(self, *args, **kwargs):
        return self._run(self._session.scalar(*args, **kwargs))

    def scalars(self, *args, **kwargs):
        return self._run(self._session.scalars(*args, **kwargs))

    def flush(self):
        return self._run(self._session.flush())

    def refresh(self, instance, attribute_names=None, with_for_update=None):
        return self._run(
            self._session.refresh(
                instance,
                attribute_names=attribute_names,
                with_for_update=with_for_update,
            )
        )

    def commit(self):
        return self._run(self._session.commit())

    def rollback(self):
        return self._run(self._session.rollback())

    def close(self):
        return self._run(self._session.close())

    def add(self, instance):
        self._session.add(instance)

    def add_all(self, instances):
        self._session.add_all(instances)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._session, item)


class _SyncSessionContext:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_context = None
        self._proxy: _SyncSessionProxy | None = None

    def __enter__(self) -> _SyncSessionProxy:
        self._loop = asyncio.new_event_loop()
        self._async_context = self._session_factory()
        session = self._loop.run_until_complete(self._async_context.__aenter__())
        self._proxy = _SyncSessionProxy(session, self._loop)
        return self._proxy

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        assert self._loop is not None
        assert self._async_context is not None
        try:
            return self._loop.run_until_complete(
                self._async_context.__aexit__(exc_type, exc, tb)
            )
        finally:
            self._loop.close()


class _SyncSessionFactoryProxy:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    def __call__(self) -> _SyncSessionContext:
        return _SyncSessionContext(self._session_factory)


def build_sync_session_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], _SyncSessionContext]:
    return _SyncSessionFactoryProxy(session_factory)


async def apply_schema_async(engine: AsyncEngine, settings: Settings) -> None:
    await run_schema_migrations(engine, settings)


def apply_schema(engine, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not isinstance(engine, AsyncEngine):
        raise TypeError(f"unsupported engine type: {type(engine)!r}")
    asyncio.run(apply_schema_async(engine, settings))


@asynccontextmanager
async def transactional_session(session_factory: async_sessionmaker[AsyncSession]):
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
