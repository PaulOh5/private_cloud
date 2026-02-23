from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.rabbitmq_rpc import RabbitMqVmProvisioningAdapter
from app.config import Settings
from app.runtime.lifecycle import WorkerLifecycleManager, WorkerSpec
from app.runtime.workers.outbox_relay import OutboxRelay
from app.runtime.workers.rabbitmq_result_consumer import RabbitMqVmResultConsumer
from app.runtime.workers.stale_task_monitor import StaleTaskMonitor


def build_worker_specs(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    vm_publisher: RabbitMqVmProvisioningAdapter,
) -> list[WorkerSpec]:
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


def build_worker_lifecycle(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> WorkerLifecycleManager:
    vm_publisher = RabbitMqVmProvisioningAdapter(settings.rabbitmq_dsn)
    return WorkerLifecycleManager(
        build_worker_specs(settings, session_factory, vm_publisher)
    )
