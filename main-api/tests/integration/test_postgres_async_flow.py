from __future__ import annotations

from datetime import datetime, timezone
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.adapters.postgres_repositories import (
    PostgresCommandOutboxRepository,
    PostgresInstanceRepository,
    PostgresRefreshTokenRepository,
    PostgresTaskRepository,
    PostgresUserRepository,
)
from app.runtime.workers.outbox_relay import OutboxRelay
from app.adapters.resource_accounting import HostResourceAccountingAdapter
from app.runtime.workers.stale_task_monitor import StaleTaskMonitor
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

    def enqueue_command(
        self,
        *,
        topic: str,
        payload: dict,
        task_id,
        request_id,
        max_attempts: int,
    ) -> None:
        self.calls.append(
            {
                "command": topic,
                "topic": topic,
                "payload": payload,
                "task_id": task_id,
                "request_id": request_id,
                "max_attempts": max_attempts,
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


@pytest.fixture
def listener_dsn(pg_container):
    return pg_container.get_connection_url(driver=None)


@pytest.mark.integration
def test_create_handler_persists_pending_instance_and_task(session_factory):
    provisioning = DummyProvisioning()

    with session_factory() as session:
        handler = CreateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            outbox_repository=provisioning,
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
def test_create_handler_with_outbox_repository_persists_outbox_row(session_factory):
    with session_factory() as session:
        handler = CreateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            outbox_repository=PostgresCommandOutboxRepository(session, notify_channel="command_outbox_wakeup"),
            outbox_max_attempts=7,
            accounting=HostResourceAccountingAdapter(session),
        )
        accepted = handler.handle(
            CreateInstanceCommand(
                cpu=2,
                memory_mib=4096,
                disk_gib=40,
                name="integration-outbox-vm",
                host_node="localhost",
            )
        )
        session.commit()

    with session_factory() as session:
        outbox_row = session.execute(
            text(
                """
                SELECT topic, status, task_id, request_id, max_attempts
                FROM command_outbox
                WHERE task_id = :task_id
                """
            ),
            {"task_id": str(accepted.task_id)},
        ).mappings().one()

    assert outbox_row["topic"] == "instance.create"
    assert outbox_row["status"] == "queued"
    assert UUID(str(outbox_row["task_id"])) == accepted.task_id
    assert outbox_row["max_attempts"] == 7


class CollectingProvisioning:
    def __init__(self):
        self.calls: list[dict] = []

    def publish_command(self, command: str, payload: dict, task_id, request_id) -> None:
        self.calls.append(
            {
                "command": command,
                "payload": payload,
                "task_id": str(task_id),
                "request_id": str(request_id),
            }
        )


@pytest.mark.integration
def test_outbox_relay_drains_and_marks_sent(session_factory, listener_dsn):
    provisioning = CollectingProvisioning()
    now = datetime.now(timezone.utc)
    outbox_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    instance_id = uuid4()
    with session_factory() as session:
        session.execute(text("DELETE FROM command_outbox"))
        session.execute(
            text(
                """
                INSERT INTO command_outbox (
                    id, topic, task_id, request_id, payload, status,
                    attempt_count, max_attempts, next_attempt_at,
                    locked_by, lock_expires_at, last_error, sent_at,
                    created_at, updated_at
                )
                VALUES (
                    :id, :topic, :task_id, :request_id, CAST(:payload AS JSONB), 'queued',
                    0, 3, :next_attempt_at,
                    NULL, NULL, NULL, NULL,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(outbox_id),
                "topic": "instance.create",
                "task_id": str(task_id),
                "request_id": str(request_id),
                "payload": f'{{"instance_id":"{instance_id}","host_node":"localhost"}}',
                "next_attempt_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        session.commit()

    relay = OutboxRelay(
        session_factory=session_factory,
        provisioning=provisioning,
        postgres_listener_dsn=listener_dsn,
        notify_channel="command_outbox_wakeup",
        poll_interval_seconds=0.1,
        batch_size=50,
        lock_timeout_seconds=10,
        retry_max_seconds=5,
    )
    processed = relay._drain_available()
    assert processed >= 1
    assert any(call["task_id"] == str(task_id) for call in provisioning.calls)

    with session_factory() as session:
        row = session.execute(
            text("SELECT status, sent_at FROM command_outbox WHERE id = :id"),
            {"id": str(outbox_id)},
        ).mappings().one()
    assert row["status"] == "sent"
    assert row["sent_at"] is not None


@pytest.mark.integration
def test_stale_monitor_ignores_outbox_not_sent_and_recovers_outbox_failed(session_factory):
    now = datetime.now(timezone.utc)
    stale_time = now.replace(microsecond=0)
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    outbox_id = uuid4()

    with session_factory() as session:
        session.execute(text("DELETE FROM command_outbox"))
        session.execute(text("DELETE FROM instance_tasks"))
        session.execute(text("DELETE FROM instances"))
        session.execute(
            text(
                """
                INSERT INTO instances (
                    id, tenant_id, name, cpu, memory_mib, disk_gib,
                    status, ip_address, host_node, reserve_resources,
                    last_task_id, deleted_at, created_at, updated_at
                )
                VALUES (
                    :id, :tenant_id, :name, :cpu, :memory_mib, :disk_gib,
                    'creating_pending', NULL, :host_node, true,
                    NULL, NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(instance_id),
                "tenant_id": DEFAULT_TENANT_ID,
                "name": "stale-monitor-vm1",
                "cpu": 1,
                "memory_mib": 1024,
                "disk_gib": 20,
                "host_node": "localhost",
                "created_at": stale_time,
                "updated_at": stale_time,
            },
        )
        session.execute(
            text(
                """
                INSERT INTO instance_tasks (
                    id, instance_id, command, status, request_id,
                    request_payload, result_payload,
                    error_code, error_message,
                    retry_of_task_id, canceled_by, cancel_reason,
                    attempt_count, max_attempts,
                    created_at, started_at, finished_at, updated_at
                )
                VALUES (
                    :id, :instance_id, 'create', 'queued', :request_id,
                    CAST(:request_payload AS JSONB), NULL,
                    NULL, NULL,
                    NULL, NULL, NULL,
                    0, 3,
                    :created_at, NULL, NULL, :updated_at
                )
                """
            ),
            {
                "id": str(task_id),
                "instance_id": str(instance_id),
                "request_id": str(request_id),
                "request_payload": '{"host_node":"localhost"}',
                "created_at": stale_time,
                "updated_at": stale_time,
            },
        )
        session.execute(
            text(
                """
                INSERT INTO command_outbox (
                    id, topic, task_id, request_id, payload, status,
                    attempt_count, max_attempts, next_attempt_at,
                    locked_by, lock_expires_at, last_error, sent_at,
                    created_at, updated_at
                )
                VALUES (
                    :id, 'instance.create', :task_id, :request_id, CAST(:payload AS JSONB), 'queued',
                    0, 3, :next_attempt_at,
                    NULL, NULL, NULL, NULL,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(outbox_id),
                "task_id": str(task_id),
                "request_id": str(request_id),
                "payload": f'{{"instance_id":"{instance_id}","host_node":"localhost"}}',
                "next_attempt_at": stale_time,
                "created_at": stale_time,
                "updated_at": stale_time,
            },
        )
        session.commit()

    monitor = StaleTaskMonitor(session_factory=session_factory, queued_timeout_seconds=1, sweep_interval_seconds=10)
    time.sleep(1.2)
    recovered = monitor._sweep_once()
    assert recovered == 0

    with session_factory() as session:
        session.execute(
            text(
                """
                UPDATE command_outbox
                SET status = 'failed',
                    last_error = 'publish failed'
                WHERE id = :id
                """
            ),
            {
                "id": str(outbox_id),
            },
        )
        session.commit()

    recovered = monitor._sweep_once()
    assert recovered == 1

    with session_factory() as session:
        task = session.execute(
            text("SELECT status, error_code FROM instance_tasks WHERE id = :id"),
            {"id": str(task_id)},
        ).mappings().one()
    assert task["status"] == "failed"
    assert task["error_code"] == "TIMEOUT"


@pytest.mark.integration
def test_update_handler_rejects_when_active_task_exists(session_factory):
    provisioning = DummyProvisioning()

    with session_factory() as session:
        create_handler = CreateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            outbox_repository=provisioning,
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
            outbox_repository=provisioning,
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
