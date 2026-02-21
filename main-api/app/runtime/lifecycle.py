from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


class RuntimeWorker(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    worker: RuntimeWorker
    requires_ready: bool = False
    ready_timeout_seconds: float = 10.0


class WorkerLifecycleManager:
    def __init__(self, workers: list[WorkerSpec]):
        self._workers = list(workers)
        self._started: list[WorkerSpec] = []

    def start_all(self) -> None:
        self._started = []
        try:
            for spec in self._workers:
                logger.info("starting worker: %s", spec.name)
                spec.worker.start()
                self._started.append(spec)

                if not spec.requires_ready:
                    continue
                if not self._wait_until_ready(spec.worker, timeout=spec.ready_timeout_seconds):
                    raise RuntimeError(f"worker {spec.name} was not ready in {spec.ready_timeout_seconds:.1f}s")
        except Exception:
            logger.exception("worker startup failed; stopping started workers")
            self.stop_all()
            raise

    def stop_all(self) -> None:
        workers = list(reversed(self._started or self._workers))
        self._started = []
        for spec in workers:
            try:
                logger.info("stopping worker: %s", spec.name)
                spec.worker.stop()
            except Exception:
                logger.exception("failed to stop worker: %s", spec.name)

    def _wait_until_ready(self, worker: RuntimeWorker, *, timeout: float) -> bool:
        wait_fn = getattr(worker, "wait_until_ready", None)
        if wait_fn is None:
            return True
        try:
            return bool(wait_fn(timeout=max(0.1, float(timeout))))
        except TypeError:
            return bool(wait_fn(max(0.1, float(timeout))))
