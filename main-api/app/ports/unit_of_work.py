from __future__ import annotations

from typing import Protocol


class UnitOfWork(Protocol):
    async def advisory_lock(self, key: int) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
