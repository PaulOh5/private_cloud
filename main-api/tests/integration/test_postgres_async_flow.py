from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.adapters.postgres import (
    PostgresInstanceRepository,
    PostgresRefreshTokenRepository,
    PostgresTaskRepository,
    PostgresUserRepository,
)
from app.adapters.resource_accounting import HostResourceAccountingAdapter
from app.application.commands.create_instance import CreateInstanceCommand, CreateInstanceHandler
from app.application.commands.update_instance import UpdateInstanceCommand, UpdateInstanceHandler
from app.domain.errors import ConflictError
from app.infra.db import apply_schema
from app.security import hash_password

postgres = pytest.importorskip("testcontainers.postgres")
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class DummyProvisioning:
    def __init__(self):
        self.calls: list[dict] = []

    def publish_command(self, command: str, payload: dict, task_id, request_id) -> None:
        self.calls.append(
            {
                "command": command,
                "payload": payload,
                "task_id": task_id,
                "request_id": request_id,
            }
        )


@pytest.fixture(scope="module")
def pg_container():
    with postgres.PostgresContainer("postgres:16") as c:
        yield c


@pytest.fixture
def session_factory(pg_container):
    engine = create_engine(pg_container.get_connection_url(driver=None).replace("postgresql://", "postgresql+psycopg://"))
    apply_schema(engine)
    sf = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False)
    with sf() as s:
        s.execute(
            text(
                """
                INSERT INTO resource_capacity (host_node, total_cpu, total_memory_mib, total_disk_gib)
                VALUES ('localhost', 64, 262144, 5000)
                ON CONFLICT (host_node) DO UPDATE
                SET total_cpu = EXCLUDED.total_cpu,
                    total_memory_mib = EXCLUDED.total_memory_mib,
                    total_disk_gib = EXCLUDED.total_disk_gib
                """
            )
        )
        s.commit()
    return sf


@pytest.mark.integration
def test_create_handler_persists_pending_instance_and_task(session_factory):
    provisioning = DummyProvisioning()

    with session_factory() as session:
        handler = CreateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            provisioning=provisioning,
            accounting=HostResourceAccountingAdapter(session),
        )
        accepted = handler.handle(
            CreateInstanceCommand(
                cpu=2,
                memory_mib=4096,
                disk_gib=40,
                name="integration-vm",
                host_node="localhost",
            )
        )
        session.commit()

    with session_factory() as session:
        instance_row = session.execute(
            text("SELECT status, reserve_resources, last_task_id FROM instances WHERE id = :id"),
            {"id": str(accepted.instance_id)},
        ).mappings().one()
        task_row = session.execute(
            text("SELECT status, command FROM instance_tasks WHERE id = :id"),
            {"id": str(accepted.task_id)},
        ).mappings().one()

    assert instance_row["status"] == "creating_pending"
    assert instance_row["reserve_resources"] is True
    assert UUID(str(instance_row["last_task_id"])) == accepted.task_id
    assert task_row["status"] == "queued"
    assert task_row["command"] == "create"
    assert provisioning.calls and provisioning.calls[0]["command"] == "instance.create"


@pytest.mark.integration
def test_update_handler_rejects_when_active_task_exists(session_factory):
    provisioning = DummyProvisioning()

    with session_factory() as session:
        create_handler = CreateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            provisioning=provisioning,
            accounting=HostResourceAccountingAdapter(session),
        )
        accepted = create_handler.handle(
            CreateInstanceCommand(
                cpu=1,
                memory_mib=1024,
                disk_gib=20,
                name="integration-vm-conflict",
                host_node="localhost",
            )
        )
        session.commit()

    with session_factory() as session:
        update_handler = UpdateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            provisioning=provisioning,
            accounting=HostResourceAccountingAdapter(session),
        )
        with pytest.raises(ConflictError):
            update_handler.handle(
                UpdateInstanceCommand(
                    instance_id=accepted.instance_id,
                    cpu=2,
                    memory_mib=2048,
                    disk_gib=30,
                    host_node="localhost",
                )
            )


@pytest.mark.integration
def test_refresh_token_repository_create_and_revoke(session_factory):
    with session_factory() as session:
        users = PostgresUserRepository(session)
        refresh_tokens = PostgresRefreshTokenRepository(session)
        user = users.ensure_user(
            username="integration-auth-user",
            password_hash=hash_password("integration-pass"),
            role="viewer",
            tenant_id=UUID(DEFAULT_TENANT_ID),
        )
        token_hash = "abc123hash"
        created = refresh_tokens.create(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        active = refresh_tokens.get_active_by_hash(token_hash)
        revoked = refresh_tokens.revoke_by_hash(token_hash)
        session.commit()

    assert created.token_hash == token_hash
    assert active is not None
    assert active.user_id == user.id
    assert revoked is not None
    assert revoked.revoked_at is not None


@pytest.mark.integration
def test_user_repository_create_list_update_and_count_admins(session_factory):
    with session_factory() as session:
        users = PostgresUserRepository(session)
        created = users.create_user(
            username="integration-user-mgmt",
            password_hash=hash_password("integration-pass-2"),
            role="operator",
            is_active=True,
            tenant_id=UUID(DEFAULT_TENANT_ID),
        )
        listed, total = users.list_users(
            limit=50,
            offset=0,
            role=None,
            is_active=True,
            username="integration-user-mgmt",
        )
        updated = users.update_user(
            user_id=created.id,
            role="admin",
            is_active=True,
            password_hash=None,
        )
        active_admins = users.count_active_admins()
        session.commit()

    assert created.role == "operator"
    assert total >= 1
    assert any(item.id == created.id for item in listed)
    assert updated.role == "admin"
    assert active_admins >= 1


@pytest.mark.integration
def test_refresh_token_repository_revoke_all_for_user(session_factory):
    with session_factory() as session:
        users = PostgresUserRepository(session)
        refresh_tokens = PostgresRefreshTokenRepository(session)
        user = users.ensure_user(
            username="integration-auth-user-revoke-all",
            password_hash=hash_password("integration-pass-3"),
            role="viewer",
            tenant_id=UUID(DEFAULT_TENANT_ID),
        )
        refresh_tokens.create(
            user_id=user.id,
            token_hash="hash-revoke-all-1",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        refresh_tokens.create(
            user_id=user.id,
            token_hash="hash-revoke-all-2",
            expires_at=datetime(2099, 1, 2, tzinfo=timezone.utc),
        )
        revoked_count = refresh_tokens.revoke_all_for_user(user.id)
        still_active_1 = refresh_tokens.get_active_by_hash("hash-revoke-all-1")
        still_active_2 = refresh_tokens.get_active_by_hash("hash-revoke-all-2")
        session.commit()

    assert revoked_count >= 2
    assert still_active_1 is None
    assert still_active_2 is None
