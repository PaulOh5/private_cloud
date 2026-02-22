from __future__ import annotations

import logging
import time
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.adapters.postgres_repositories import PostgresTenantQuotaRepository, PostgresUserRepository
from app.config import Settings
from app.infra.db import apply_schema, build_engine, build_session_factory
from app.security import hash_password

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_KEY = "default"
DEFAULT_TENANT_NAME = "Default Tenant"


def run_with_db_retry(
    description: str,
    fn: Callable[[], None],
    attempts: int = 20,
    delay_seconds: float = 1.0,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            fn()
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
            time.sleep(delay_seconds)


def bootstrap_data(session_factory, settings: Settings) -> None:
    with session_factory() as session:
        session.execute(
            text(
                """
                INSERT INTO tenants (id, key, name, is_active, created_at, updated_at)
                VALUES (:id, :key, :name, true, NOW(), NOW())
                ON CONFLICT (key) DO UPDATE
                  SET name = EXCLUDED.name,
                      is_active = true,
                      updated_at = NOW()
                """
            ),
            {
                "id": DEFAULT_TENANT_ID,
                "key": DEFAULT_TENANT_KEY,
                "name": DEFAULT_TENANT_NAME,
            },
        )
        session.execute(
            text(
                """
                INSERT INTO resource_capacity (host_node, total_cpu, total_memory_mib, total_disk_gib)
                VALUES (:host_node, :total_cpu, :total_memory_mib, :total_disk_gib)
                ON CONFLICT (host_node) DO UPDATE
                  SET total_cpu = EXCLUDED.total_cpu,
                      total_memory_mib = EXCLUDED.total_memory_mib,
                      total_disk_gib = EXCLUDED.total_disk_gib
                """
            ),
            {
                "host_node": settings.host_node,
                "total_cpu": settings.total_cpu,
                "total_memory_mib": settings.total_memory_mib,
                "total_disk_gib": settings.total_disk_gib,
            },
        )
        PostgresTenantQuotaRepository(session).upsert(
            tenant_id=UUID(DEFAULT_TENANT_ID),
            max_instances=settings.total_instances,
            max_cpu=settings.total_cpu,
            max_memory_mib=settings.total_memory_mib,
            max_disk_gib=settings.total_disk_gib,
        )
        PostgresUserRepository(session).ensure_user(
            username=settings.bootstrap_admin_username,
            password_hash=hash_password(settings.bootstrap_admin_password),
            role=settings.bootstrap_admin_role,
            tenant_id=None,
        )
        session.commit()


def initialize_database(settings: Settings):
    engine = build_engine(settings)
    run_with_db_retry("apply_schema", lambda: apply_schema(engine))
    session_factory = build_session_factory(engine)
    run_with_db_retry("bootstrap_data", lambda: bootstrap_data(session_factory, settings))
    return engine, session_factory
