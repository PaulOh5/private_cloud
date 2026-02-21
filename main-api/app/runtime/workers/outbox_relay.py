from __future__ import annotations

import logging
import random
import re
import socket
import threading
from uuid import uuid4

import psycopg
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.postgres_repositories import PostgresCommandOutboxRepository
from app.domain.models import OutboxMessage
from app.ports import VmProvisioningPort

logger = logging.getLogger(__name__)
_CHANNEL_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OutboxRelay:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        provisioning: VmProvisioningPort,
        postgres_listener_dsn: str,
        notify_channel: str,
        poll_interval_seconds: float,
        batch_size: int,
        lock_timeout_seconds: int,
        retry_max_seconds: int,
    ):
        if not _CHANNEL_NAME_PATTERN.match(notify_channel):
            raise ValueError(f"invalid notify channel name: {notify_channel}")

        self.session_factory = session_factory
        self.provisioning = provisioning
        self.postgres_listener_dsn = postgres_listener_dsn
        self.notify_channel = notify_channel
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self.batch_size = max(1, int(batch_size))
        self.lock_timeout_seconds = max(1, int(lock_timeout_seconds))
        self.retry_max_seconds = max(1, int(retry_max_seconds))
        self.locker_id = f"{socket.gethostname()}:{uuid4()}"

        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._thread = threading.Thread(target=self._run, name="outbox-relay", daemon=True)
        self._thread.start()

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        return self._ready_event.wait(timeout=timeout)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._ready_event.clear()

    def _open_listener(self):
        conn = psycopg.connect(self.postgres_listener_dsn, autocommit=True)
        with conn.cursor() as cursor:
            cursor.execute(f"LISTEN {self.notify_channel}")
        return conn

    def _wait_for_notify(self, conn) -> bool:
        try:
            for _notify in conn.notifies(timeout=self.poll_interval_seconds, stop_after=1):
                return True
            return False
        except Exception:
            logger.exception("outbox relay listener failed")
            raise

    def _run(self) -> None:
        self._ready_event.set()
        listener = None
        while not self._stop_event.is_set():
            try:
                processed = self._drain_available()
            except Exception:
                logger.exception("outbox relay drain failed")
                self._stop_event.wait(self.poll_interval_seconds)
                continue

            if processed > 0:
                continue

            try:
                if listener is None or listener.closed:
                    listener = self._open_listener()
                self._wait_for_notify(listener)
            except Exception:
                try:
                    if listener is not None:
                        listener.close()
                except Exception:
                    pass
                listener = None
                self._stop_event.wait(self.poll_interval_seconds)

        try:
            if listener is not None:
                listener.close()
        except Exception:
            pass

    def _drain_available(self) -> int:
        total_processed = 0
        while not self._stop_event.is_set():
            with self.session_factory() as session:
                outbox_repo = PostgresCommandOutboxRepository(session)
                outbox_repo.recover_stuck_publishing()
                messages = outbox_repo.claim_batch(
                    locker_id=self.locker_id,
                    limit=self.batch_size,
                    lock_timeout_seconds=self.lock_timeout_seconds,
                )
                session.commit()

            if not messages:
                break

            for message in messages:
                if self._stop_event.is_set():
                    break
                self._dispatch(message)
                total_processed += 1
        return total_processed

    def _dispatch(self, message: OutboxMessage) -> None:
        try:
            self.provisioning.publish_command(
                command=message.topic,
                payload=message.payload,
                task_id=message.task_id,
                request_id=message.request_id,
            )
            with self.session_factory() as session:
                PostgresCommandOutboxRepository(session).mark_sent(message.id)
                session.commit()
            return
        except Exception as exc:
            logger.exception("outbox publish failed: id=%s topic=%s", message.id, message.topic)
            error_message = str(exc)[:2000] if str(exc) else "publish failed"

        attempt_after_failure = message.attempt_count + 1
        with self.session_factory() as session:
            outbox_repo = PostgresCommandOutboxRepository(session)
            if attempt_after_failure >= message.max_attempts:
                outbox_repo.mark_failed(message.id, error_message=error_message)
            else:
                outbox_repo.mark_retry(
                    message.id,
                    delay_seconds=self._retry_delay_seconds(attempt_after_failure),
                    error_message=error_message,
                )
            session.commit()

    def _retry_delay_seconds(self, attempt: int) -> int:
        base = min(self.retry_max_seconds, 2 ** max(1, attempt))
        jitter = random.uniform(0.0, min(1.0, base * 0.25))
        return max(1, int(base + jitter))
