import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.adapters.postgres_repositories import PostgresTenantQuotaRepository, PostgresUserRepository
from app.adapters.rabbitmq_image_sync_rpc import RabbitMqVmImageSyncRpcAdapter
from app.adapters.rabbitmq_rpc import RabbitMqVmProvisioningAdapter
from app.adapters.console_ticket_store import ConsoleTicketStore
from app.runtime.lifecycle import WorkerLifecycleManager, WorkerSpec
from app.runtime.workers.outbox_relay import OutboxRelay
from app.runtime.workers.rabbitmq_result_consumer import RabbitMqVmResultConsumer
from app.runtime.workers.stale_task_monitor import StaleTaskMonitor
from app.api.auth_routes import auth_router
from app.api.audit_routes import audit_router
from app.api.routes import image_router, instance_router, legacy_image_router, task_router
from app.api.tenant_routes import tenant_router
from app.api.user_routes import role_router, user_router
from app.application.services.vm_image_catalog import load_vm_image_catalog
from app.config import get_settings
from app.domain.errors import DomainError
from app.infra.db import apply_schema, build_engine, build_session_factory
from app.security import hash_password

logger = logging.getLogger(__name__)
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_KEY = "default"
DEFAULT_TENANT_NAME = "Default Tenant"


def _run_with_db_retry(description: str, fn: Callable[[], None], attempts: int = 20, delay_seconds: float = 1.0) -> None:
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


def _bootstrap_data(session_factory, settings) -> None:
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


def _initialize_database(settings):
    engine = build_engine(settings)
    _run_with_db_retry("apply_schema", lambda: apply_schema(engine))
    session_factory = build_session_factory(engine)
    _run_with_db_retry("bootstrap_data", lambda: _bootstrap_data(session_factory, settings))
    return engine, session_factory


def _build_worker_specs(settings, session_factory, vm_publisher) -> list[WorkerSpec]:
    worker_specs: list[WorkerSpec] = [
        WorkerSpec(
            name="vm-result-consumer",
            worker=RabbitMqVmResultConsumer(settings.rabbitmq_dsn, session_factory),
            requires_ready=settings.outbox_relay_enabled,
            ready_timeout_seconds=10.0,
        )
    ]
    if settings.outbox_relay_enabled:
        worker_specs.append(
            WorkerSpec(
                name="outbox-relay",
                worker=OutboxRelay(
                    session_factory=session_factory,
                    provisioning=vm_publisher,
                    postgres_listener_dsn=settings.postgres_listener_dsn,
                    notify_channel=settings.outbox_notify_channel,
                    poll_interval_seconds=settings.outbox_poll_interval_seconds,
                    batch_size=settings.outbox_batch_size,
                    lock_timeout_seconds=settings.outbox_lock_timeout_seconds,
                    retry_max_seconds=settings.outbox_retry_max_seconds,
                ),
            )
        )
    if settings.task_stale_sweep_interval_seconds > 0:
        worker_specs.append(
            WorkerSpec(
                name="stale-task-monitor",
                worker=StaleTaskMonitor(
                    session_factory=session_factory,
                    queued_timeout_seconds=settings.task_stale_queued_timeout_seconds,
                    sweep_interval_seconds=settings.task_stale_sweep_interval_seconds,
                ),
            )
        )
    return worker_specs


def _build_lifespan(worker_lifecycle: WorkerLifecycleManager):
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            worker_lifecycle.start_all()
            yield
        finally:
            worker_lifecycle.stop_all()

    return lifespan


def _configure_app_state(app: FastAPI, settings, engine, session_factory, vm_publisher, vm_image_catalog) -> None:
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.vm_publisher = vm_publisher
    app.state.vm_port = vm_publisher
    app.state.vm_image_sync_port = RabbitMqVmImageSyncRpcAdapter(
        settings.rabbitmq_dsn,
        settings.vm_command_timeout_seconds,
    )
    app.state.console_ticket_store = ConsoleTicketStore()
    app.state.vm_image_catalog = vm_image_catalog


def _register_routers(app: FastAPI) -> None:
    app.include_router(auth_router)
    app.include_router(audit_router)
    app.include_router(role_router)
    app.include_router(user_router)
    app.include_router(tenant_router)
    app.include_router(image_router)
    app.include_router(legacy_image_router)
    app.include_router(instance_router)
    app.include_router(task_router)


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    def handle_domain_error(_: Request, exc: DomainError):
        mapping = {
            "VALIDATION_ERROR": 400,
            "CAPACITY_EXCEEDED": 409,
            "QUOTA_EXCEEDED": 409,
            "QUOTA_CONFLICT": 409,
            "TENANT_INACTIVE": 403,
            "VM_NOT_FOUND": 404,
            "CONFLICT": 409,
            "QEMU_ERROR": 502,
            "TIMEOUT": 504,
        }
        return JSONResponse(
            status_code=mapping.get(exc.code, 500),
            content={"code": exc.code, "message": str(exc)},
        )


def create_app() -> FastAPI:
    settings = get_settings()
    vm_image_catalog = load_vm_image_catalog(settings)
    engine, session_factory = _initialize_database(settings)
    vm_publisher = RabbitMqVmProvisioningAdapter(settings.rabbitmq_dsn)
    worker_lifecycle = WorkerLifecycleManager(_build_worker_specs(settings, session_factory, vm_publisher))

    app = FastAPI(title=settings.app_name, lifespan=_build_lifespan(worker_lifecycle))
    _configure_app_state(app, settings, engine, session_factory, vm_publisher, vm_image_catalog)
    _register_routers(app)
    _register_exception_handlers(app)

    return app


app = create_app()
