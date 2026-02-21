from __future__ import annotations

from typing import Protocol


class UnitOfWork(Protocol):
    def advisory_lock(self, key: int) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...
