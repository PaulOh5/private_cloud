from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, text


def apply_sql_schema(engine: Engine) -> None:
    schema_file = Path(__file__).resolve().parents[2] / "migrations" / "001_init.sql"
    sql = schema_file.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))


def apply_schema(engine: Engine) -> None:
    apply_sql_schema(engine)
