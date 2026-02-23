from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings


async def apply_schema(engine: AsyncEngine, settings: Settings) -> None:
    del engine
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.postgres_sync_dsn)
    command.upgrade(cfg, "head")
