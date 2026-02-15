from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.postgres import PostgresInstanceRepository, PostgresTaskRepository
from app.domain.models import ResourceSpec

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
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="stale-task-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
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
                        SELECT id
                        FROM instance_tasks
                        WHERE status = 'queued'
                          AND created_at < :cutoff
                        ORDER BY created_at ASC
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

                self._revert_instance_state(instance_repo, task.instance_id, task.command, task.request_payload)
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

    def _revert_instance_state(
        self,
        instance_repo: PostgresInstanceRepository,
        instance_id: UUID,
        command: str,
        request_payload: dict,
    ) -> None:
        instance = instance_repo.get_for_update(instance_id)
        if not instance:
            return

        if command == "create":
            instance_repo.update_state(
                instance_id,
                status="error",
                reserve_resources=False,
                last_task_id=None,
                deleted_at=None,
                ip_address=None,
            )
            return

        if command == "update":
            previous_spec = request_payload.get("previous_spec", {})
            spec = ResourceSpec(
                cpu=int(previous_spec.get("cpu", 1)),
                memory_mib=int(previous_spec.get("memory_mib", 512)),
                disk_gib=int(previous_spec.get("disk_gib", 10)),
            )
            instance_repo.update_spec(
                instance_id,
                spec=spec,
                status="error",
                ip_address=request_payload.get("previous_ip_address"),
                reserve_resources=True,
                last_task_id=None,
                deleted_at=request_payload.get("previous_deleted_at"),
            )
            return

        if command == "delete":
            previous_spec = request_payload.get("previous_spec", {})
            spec = ResourceSpec(
                cpu=int(previous_spec.get("cpu", 1)),
                memory_mib=int(previous_spec.get("memory_mib", 512)),
                disk_gib=int(previous_spec.get("disk_gib", 10)),
            )
            instance_repo.update_spec(
                instance_id,
                spec=spec,
                status="error",
                ip_address=request_payload.get("previous_ip_address"),
                reserve_resources=True,
                last_task_id=None,
                deleted_at=None,
            )
