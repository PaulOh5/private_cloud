from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.console_ticket_store import ConsoleTicketStore
from app.adapters.rabbitmq_image_sync_rpc import RabbitMqVmImageSyncRpcAdapter
from app.adapters.rabbitmq_rpc import RabbitMqVmProvisioningAdapter
from app.api.error_handlers import register_exception_handlers
from app.api.routers import (
    audit_router,
    auth_router,
    image_router,
    instance_router,
    legacy_image_router,
    role_router,
    task_router,
    tenant_router,
    user_router,
)
from app.application.services.vm_image_catalog import load_vm_image_catalog
from app.bootstrap.database import initialize_database
from app.bootstrap.workers import build_worker_lifecycle
from app.config import Settings, get_settings


def _build_lifespan(worker_lifecycle):
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            worker_lifecycle.start_all()
            yield
        finally:
            worker_lifecycle.stop_all()

    return lifespan


def _configure_app_state(app: FastAPI, settings: Settings, engine, session_factory, vm_publisher, vm_image_catalog) -> None:
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


def create_api_app(*, include_workers: bool = False, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    vm_image_catalog = load_vm_image_catalog(settings)
    engine, session_factory = initialize_database(settings)
    vm_publisher = RabbitMqVmProvisioningAdapter(settings.rabbitmq_dsn)

    lifespan = None
    if include_workers:
        worker_lifecycle = build_worker_lifecycle(settings, session_factory)
        lifespan = _build_lifespan(worker_lifecycle)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    _configure_app_state(app, settings, engine, session_factory, vm_publisher, vm_image_catalog)
    _register_routers(app)
    register_exception_handlers(app)
    return app
