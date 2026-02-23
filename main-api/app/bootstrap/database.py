from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError

from app.adapters.postgres_repositories import (
    PostgresTenantQuotaRepository,
    PostgresUserRepository,
)
from app.adapters.postgres_repositories.orm.resource import ResourceCapacityModel
from app.adapters.postgres_repositories.orm.tenant import TenantModel
from app.config import Settings
from app.infra.db import apply_schema_async, build_engine, build_session_factory
from app.security import hash_password

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_KEY = "default"
DEFAULT_TENANT_NAME = "Default Tenant"


async def run_with_db_retry(
    description: str,
    fn: Callable[[], Awaitable[None]],
    attempts: int = 20,
    delay_seconds: float = 1.0,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await fn()
            return
        except OperationalError:
            if attempt == attempts:
                raise
            logger.warning(
                "Database operation failed during startup (%s): retrying %s/%s in %.1fs",
                description,
                attempt,
                attempts,
                delay_seconds,
            )
            await asyncio.sleep(delay_seconds)


async def bootstrap_data(session_factory, settings: Settings) -> None:
    async with session_factory() as session:
        now = datetime.now(timezone.utc)
        await session.execute(
            pg_insert(TenantModel)
            .values(
                id=UUID(DEFAULT_TENANT_ID),
                key=DEFAULT_TENANT_KEY,
                name=DEFAULT_TENANT_NAME,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[TenantModel.key],
                set_={
                    "name": DEFAULT_TENANT_NAME,
                    "is_active": True,
                    "updated_at": now,
                },
            )
        )
        await session.execute(
            pg_insert(ResourceCapacityModel)
            .values(
                host_node=settings.host_node,
                total_cpu=settings.total_cpu,
                total_memory_mib=settings.total_memory_mib,
                total_disk_gib=settings.total_disk_gib,
            )
            .on_conflict_do_update(
                index_elements=[ResourceCapacityModel.host_node],
                set_={
                    "total_cpu": settings.total_cpu,
                    "total_memory_mib": settings.total_memory_mib,
                    "total_disk_gib": settings.total_disk_gib,
                },
            )
        )
        await PostgresTenantQuotaRepository(session).upsert(
            tenant_id=UUID(DEFAULT_TENANT_ID),
            max_instances=settings.total_instances,
            max_cpu=settings.total_cpu,
            max_memory_mib=settings.total_memory_mib,
            max_disk_gib=settings.total_disk_gib,
        )
        await PostgresUserRepository(session).ensure_user(
            username=settings.bootstrap_admin_username,
            password_hash=hash_password(settings.bootstrap_admin_password),
            role=settings.bootstrap_admin_role,
            tenant_id=None,
        )
        await session.commit()


async def initialize_database_async(settings: Settings):
    engine = build_engine(settings)
    await run_with_db_retry(
        "apply_schema", lambda: apply_schema_async(engine, settings)
    )
    session_factory = build_session_factory(engine)
    await run_with_db_retry(
        "bootstrap_data", lambda: bootstrap_data(session_factory, settings)
    )
    return engine, session_factory


def initialize_database(settings: Settings):
    return asyncio.run(initialize_database_async(settings))
