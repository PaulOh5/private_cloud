from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, exists, literal, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.postgres_repositories import (
    PostgresInstanceRepository,
    PostgresTaskRepository,
)
from app.adapters.postgres_repositories.orm.outbox import CommandOutboxModel
from app.adapters.postgres_repositories.orm.task import InstanceTaskModel
from app.application.services.task_instance_state import (
    revert_instance_state_on_terminal_failure,
)

logger = logging.getLogger(__name__)


class StaleTaskMonitor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queued_timeout_seconds: int,
        sweep_interval_seconds: int,
    ):
        self.session_factory = session_factory
        self.queued_timeout_seconds = max(1, int(queued_timeout_seconds))
        self.sweep_interval_seconds = max(1, int(sweep_interval_seconds))
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._thread = threading.Thread(
            target=self._run_thread, name="stale-task-monitor", daemon=True
        )
        self._thread.start()

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        return self._ready_event.wait(timeout=timeout)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._ready_event.clear()

    def _run_thread(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        self._ready_event.set()
        while not self._stop_event.is_set():
            try:
                recovered = await self._sweep_once()
                if recovered > 0:
                    logger.warning(
                        "stale-task-monitor recovered %d queued task(s)", recovered
                    )
            except Exception:
                logger.exception("stale-task-monitor sweep failed")
            await asyncio.sleep(self.sweep_interval_seconds)

    async def _sweep_once(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.queued_timeout_seconds
        )
        recovered = 0

        async with self.session_factory() as session:
            topic_expr = literal("instance.") + InstanceTaskModel.command
            outbox_exists = exists(
                select(CommandOutboxModel.id).where(
                    and_(
                        CommandOutboxModel.task_id == InstanceTaskModel.id,
                        CommandOutboxModel.topic == topic_expr,
                    )
                )
            )
            stale_outbox_exists = exists(
                select(CommandOutboxModel.id).where(
                    and_(
                        CommandOutboxModel.task_id == InstanceTaskModel.id,
                        CommandOutboxModel.topic == topic_expr,
                        or_(
                            and_(
                                CommandOutboxModel.status == "sent",
                                CommandOutboxModel.sent_at.is_not(None),
                                CommandOutboxModel.sent_at < cutoff,
                            ),
                            CommandOutboxModel.status == "failed",
                        ),
                    )
                )
            )
            stale_stmt = (
                select(InstanceTaskModel.id)
                .where(
                    and_(
                        InstanceTaskModel.status == "queued",
                        InstanceTaskModel.created_at < cutoff,
                        or_(not_(outbox_exists), stale_outbox_exists),
                    )
                )
                .order_by(InstanceTaskModel.created_at.asc())
                .limit(100)
                .with_for_update(skip_locked=True)
            )
            stale_ids = [row[0] for row in (await session.execute(stale_stmt)).all()]

            if not stale_ids:
                await session.rollback()
                return 0

            task_repo = PostgresTaskRepository(session)
            instance_repo = PostgresInstanceRepository(session)

            for task_id in stale_ids:
                task = await task_repo.get_for_update(UUID(str(task_id)))
                if not task or task.status != "queued":
                    continue

                await revert_instance_state_on_terminal_failure(
                    instance_repo=instance_repo,
                    instance_id=task.instance_id,
                    command=task.command,
                    request_payload=task.request_payload,
                )
                await task_repo.mark_terminal(
                    task.id,
                    status="failed",
                    attempt_count=max(task.attempt_count, 1),
                    result_payload=None,
                    error_code="TIMEOUT",
                    error_message=f"task stayed queued for more than {self.queued_timeout_seconds}s",
                )
                recovered += 1

            await session.commit()
        return recovered
