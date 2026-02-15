import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.adapters.postgres import PostgresUserRepository
from app.adapters.rabbitmq_result_consumer import RabbitMqVmResultConsumer
from app.adapters.rabbitmq_rpc import RabbitMqVmProvisioningAdapter
from app.adapters.stale_task_monitor import StaleTaskMonitor
from app.api.auth_routes import auth_router
from app.api.audit_routes import audit_router
from app.api.routes import instance_router, task_router
from app.api.user_routes import role_router, user_router
from app.config import get_settings
from app.domain.errors import DomainError
from app.infra.db import apply_schema, build_engine, build_session_factory
from app.security import hash_password

logger = logging.getLogger(__name__)


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


def create_app() -> FastAPI:
    settings = get_settings()
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.result_consumer.start()
        if app.state.stale_task_monitor is not None:
            app.state.stale_task_monitor.start()
        try:
            yield
        finally:
            if app.state.stale_task_monitor is not None:
                app.state.stale_task_monitor.stop()
            app.state.result_consumer.stop()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    engine = build_engine(settings)

    _run_with_db_retry("apply_schema", lambda: apply_schema(engine))
    session_factory = build_session_factory(engine)

    def bootstrap_data() -> None:
        with session_factory() as session:
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
            PostgresUserRepository(session).ensure_user(
                username=settings.bootstrap_admin_username,
                password_hash=hash_password(settings.bootstrap_admin_password),
                role=settings.bootstrap_admin_role,
            )
            session.commit()

    _run_with_db_retry("bootstrap_data", bootstrap_data)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.vm_port = RabbitMqVmProvisioningAdapter(settings.rabbitmq_dsn)
    app.state.result_consumer = RabbitMqVmResultConsumer(settings.rabbitmq_dsn, session_factory)
    if settings.task_stale_sweep_interval_seconds > 0:
        app.state.stale_task_monitor = StaleTaskMonitor(
            session_factory=session_factory,
            queued_timeout_seconds=settings.task_stale_queued_timeout_seconds,
            sweep_interval_seconds=settings.task_stale_sweep_interval_seconds,
        )
    else:
        app.state.stale_task_monitor = None

    app.include_router(auth_router)
    app.include_router(audit_router)
    app.include_router(role_router)
    app.include_router(user_router)
    app.include_router(instance_router)
    app.include_router(task_router)

    @app.exception_handler(DomainError)
    def handle_domain_error(_: Request, exc: DomainError):
        mapping = {
            "VALIDATION_ERROR": 400,
            "CAPACITY_EXCEEDED": 409,
            "VM_NOT_FOUND": 404,
            "CONFLICT": 409,
            "QEMU_ERROR": 502,
            "TIMEOUT": 504,
        }
        return JSONResponse(
            status_code=mapping.get(exc.code, 500),
            content={"code": exc.code, "message": str(exc)},
        )

    return app


app = create_app()
