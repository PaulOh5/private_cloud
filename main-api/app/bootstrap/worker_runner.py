from __future__ import annotations

import logging
import signal
import threading

from app.bootstrap.database import initialize_database
from app.bootstrap.workers import build_worker_lifecycle
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def run_worker_process(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    _, session_factory = initialize_database(settings)
    lifecycle = build_worker_lifecycle(settings, session_factory)

    stop_event = threading.Event()

    def _signal_handler(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    lifecycle.start_all()
    logger.info("worker process started")
    try:
        stop_event.wait()
    finally:
        lifecycle.stop_all()
        logger.info("worker process stopped")
