"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-02-23
"""

from __future__ import annotations

from pathlib import Path

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_file = Path(__file__).resolve().parents[2] / "migrations" / "001_init.sql"
    op.execute(sa.text(sql_file.read_text(encoding="utf-8")))


def downgrade() -> None:
    op.execute(sa.text("""
    DROP VIEW IF EXISTS tenant_resource_usage_view;
    DROP VIEW IF EXISTS resource_reservations_view;
    DROP TABLE IF EXISTS audit_logs;
    DROP TABLE IF EXISTS refresh_tokens;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS command_outbox;
    DROP TABLE IF EXISTS instance_tasks;
    DROP TABLE IF EXISTS resource_capacity;
    DROP TABLE IF EXISTS instances;
    DROP TABLE IF EXISTS tenant_quotas;
    DROP TABLE IF EXISTS tenants;
    """))
