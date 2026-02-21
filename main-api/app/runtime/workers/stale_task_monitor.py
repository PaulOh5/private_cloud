from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.postgres_repositories import PostgresInstanceRepository, PostgresTaskRepository
from app.application.services.task_instance_state import revert_instance_state_on_terminal_failure

logger = logging.getLogger(__name__)


class StaleTaskMonitor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
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
        self._thread = threading.Thread(target=self._run, name="stale-task-monitor", daemon=True)
        self._thread.start()

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        return self._ready_event.wait(timeout=timeout)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._ready_event.clear()

    def _run(self) -> None:
        self._ready_event.set()
        while not self._stop_event.is_set():
            try:
                recovered = self._sweep_once()
                if recovered > 0:
                    logger.warning("stale-task-monitor recovered %d queued task(s)", recovered)
            except Exception:
                logger.exception("stale-task-monitor sweep failed")
            self._stop_event.wait(self.sweep_interval_seconds)

    def _sweep_once(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.queued_timeout_seconds)
        recovered = 0

        with self.session_factory() as session:
            stale_ids = [
                UUID(str(row["id"]))
                for row in session.execute(
                    text(
                        """
                        SELECT t.id
                        FROM instance_tasks t
                        WHERE t.status = 'queued'
                          AND t.created_at < :cutoff
                          AND (
                              NOT EXISTS (
                                  SELECT 1
                                  FROM command_outbox o
                                  WHERE o.task_id = t.id
                                    AND o.topic = ('instance.' || t.command)
                              )
                              OR EXISTS (
                                  SELECT 1
                                  FROM command_outbox o
                                  WHERE o.task_id = t.id
                                    AND o.topic = ('instance.' || t.command)
                                    AND (
                                        (
                                            o.status = 'sent'
                                            AND o.sent_at IS NOT NULL
                                            AND o.sent_at < :cutoff
                                        )
                                        OR o.status = 'failed'
                                    )
                              )
                          )
                        ORDER BY t.created_at ASC
                        LIMIT 100
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {"cutoff": cutoff},
                ).mappings().all()
            ]

            if not stale_ids:
                session.rollback()
                return 0

            task_repo = PostgresTaskRepository(session)
            instance_repo = PostgresInstanceRepository(session)

            for task_id in stale_ids:
                task = task_repo.get_for_update(task_id)
                if not task or task.status != "queued":
                    continue

                revert_instance_state_on_terminal_failure(
                    instance_repo=instance_repo,
                    instance_id=task.instance_id,
                    command=task.command,
                    request_payload=task.request_payload,
                )
                task_repo.mark_terminal(
                    task.id,
                    status="failed",
                    attempt_count=max(task.attempt_count, 1),
                    result_payload=None,
                    error_code="TIMEOUT",
                    error_message=f"task stayed queued for more than {self.queued_timeout_seconds}s",
                )
                recovered += 1

            session.commit()
        return recovered
