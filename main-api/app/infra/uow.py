from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ports import UnitOfWork


class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, session: Session):
        self.session = session

    def advisory_lock(self, key: int) -> None:
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
