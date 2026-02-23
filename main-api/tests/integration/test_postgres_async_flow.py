from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.postgres_repositories import (
    PostgresCommandOutboxRepository,
    PostgresInstanceRepository,
    PostgresRefreshTokenRepository,
    PostgresTaskRepository,
    PostgresUserRepository,
)
from app.adapters.postgres_repositories.orm.enums import (
    InstanceStatusEnum,
    OutboxStatusEnum,
    TaskCommandEnum,
    TaskStatusEnum,
)
from app.adapters.postgres_repositories.orm.instance import InstanceModel
from app.adapters.postgres_repositories.orm.outbox import CommandOutboxModel
from app.adapters.postgres_repositories.orm.resource import ResourceCapacityModel
from app.adapters.postgres_repositories.orm.task import InstanceTaskModel
from app.adapters.resource_accounting import HostResourceAccountingAdapter
from app.application.commands.instance_commands import (
    CreateInstanceCommand,
    CreateInstanceHandler,
    UpdateInstanceCommand,
    UpdateInstanceHandler,
)
from app.config import Settings
from app.domain.errors import ConflictError
from app.infra.db import apply_schema_async
from app.runtime.workers.outbox_relay import OutboxRelay
from app.runtime.workers.stale_task_monitor import StaleTaskMonitor
from app.security import hash_password

postgres = pytest.importorskip("testcontainers.postgres")
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


class DummyProvisioning:
    def __init__(self):
        self.calls: list[dict] = []

    async def enqueue_command(
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


class CollectingProvisioning:
    def __init__(self):
        self.calls: list[dict] = []

    async def publish_command(
        self, command: str, payload: dict, task_id, request_id
    ) -> None:
        self.calls.append(
            {
                "command": command,
                "payload": payload,
                "task_id": str(task_id),
                "request_id": str(request_id),
            }
        )


@pytest.fixture(scope="module")
def pg_container():
    with postgres.PostgresContainer("postgres:16") as c:
        yield c


@pytest_asyncio.fixture
async def session_factory(pg_container):
    parsed = urlparse(pg_container.get_connection_url(driver=None))
    settings = Settings(
        postgres_user=parsed.username or "test",
        postgres_password=parsed.password or "test",
        postgres_db=parsed.path.lstrip("/") or "test",
        postgres_host=parsed.hostname or "localhost",
        postgres_port=parsed.port or 5432,
    )

    engine = create_async_engine(settings.postgres_async_dsn)
    await apply_schema_async(engine, settings)
    sf = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async with sf() as session:
        await session.execute(
            pg_insert(ResourceCapacityModel)
            .values(
                host_node="localhost",
                total_cpu=64,
                total_memory_mib=262144,
                total_disk_gib=5000,
            )
            .on_conflict_do_update(
                index_elements=[ResourceCapacityModel.host_node],
                set_={
                    "total_cpu": 64,
                    "total_memory_mib": 262144,
                    "total_disk_gib": 5000,
                },
            )
        )
        await session.commit()

    yield sf
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_handler_persists_pending_instance_and_task(session_factory):
    provisioning = DummyProvisioning()

    async with session_factory() as session:
        handler = CreateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            outbox_repository=provisioning,
            accounting=HostResourceAccountingAdapter(session),
        )
        accepted = await handler.handle(
            CreateInstanceCommand(
                cpu=2,
                memory_mib=4096,
                disk_gib=40,
                name="integration-vm",
                host_node="localhost",
            )
        )
        await session.commit()

    async with session_factory() as session:
        instance_row = await session.scalar(
            select(InstanceModel).where(InstanceModel.id == accepted.instance_id)
        )
        task_row = await session.scalar(
            select(InstanceTaskModel).where(InstanceTaskModel.id == accepted.task_id)
        )

    assert instance_row is not None
    assert task_row is not None
    assert _enum_value(instance_row.status) == "creating_pending"
    assert instance_row.reserve_resources is True
    assert instance_row.last_task_id == accepted.task_id
    assert _enum_value(task_row.status) == "queued"
    assert _enum_value(task_row.command) == "create"
    assert provisioning.calls and provisioning.calls[0]["command"] == "instance.create"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_handler_with_outbox_repository_persists_outbox_row(
    session_factory,
):
    async with session_factory() as session:
        handler = CreateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            outbox_repository=PostgresCommandOutboxRepository(
                session, notify_channel="command_outbox_wakeup"
            ),
            outbox_max_attempts=7,
            accounting=HostResourceAccountingAdapter(session),
        )
        accepted = await handler.handle(
            CreateInstanceCommand(
                cpu=2,
                memory_mib=4096,
                disk_gib=40,
                name="integration-outbox-vm",
                host_node="localhost",
            )
        )
        await session.commit()

    async with session_factory() as session:
        outbox_row = await session.scalar(
            select(CommandOutboxModel).where(
                CommandOutboxModel.task_id == accepted.task_id
            )
        )

    assert outbox_row is not None
    assert outbox_row.topic == "instance.create"
    assert _enum_value(outbox_row.status) == "queued"
    assert outbox_row.task_id == accepted.task_id
    assert outbox_row.max_attempts == 7


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_relay_drains_and_marks_sent(session_factory):
    provisioning = CollectingProvisioning()
    now = datetime.now(timezone.utc)
    outbox_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    instance_id = uuid4()

    async with session_factory() as session:
        await session.execute(delete(CommandOutboxModel))
        session.add(
            CommandOutboxModel(
                id=outbox_id,
                topic="instance.create",
                task_id=task_id,
                request_id=request_id,
                payload={"instance_id": str(instance_id), "host_node": "localhost"},
                status=OutboxStatusEnum.QUEUED,
                attempt_count=0,
                max_attempts=3,
                next_attempt_at=now,
                locked_by=None,
                lock_expires_at=None,
                last_error=None,
                sent_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    relay = OutboxRelay(
        session_factory=session_factory,
        provisioning=provisioning,
        notify_channel="command_outbox_wakeup",
        poll_interval_seconds=0.1,
        batch_size=50,
        lock_timeout_seconds=10,
        retry_max_seconds=5,
    )
    processed = await relay._drain_available()
    assert processed >= 1
    assert any(call["task_id"] == str(task_id) for call in provisioning.calls)

    async with session_factory() as session:
        row = await session.scalar(
            select(CommandOutboxModel).where(CommandOutboxModel.id == outbox_id)
        )
    assert row is not None
    assert _enum_value(row.status) == "sent"
    assert row.sent_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_monitor_ignores_outbox_not_sent_and_recovers_outbox_failed(
    session_factory,
):
    now = datetime.now(timezone.utc)
    stale_time = now.replace(microsecond=0)
    instance_id = uuid4()
    task_id = uuid4()
    request_id = uuid4()
    outbox_id = uuid4()

    async with session_factory() as session:
        await session.execute(delete(CommandOutboxModel))
        await session.execute(delete(InstanceTaskModel))
        await session.execute(delete(InstanceModel))
        session.add(
            InstanceModel(
                id=instance_id,
                tenant_id=UUID(DEFAULT_TENANT_ID),
                name="stale-monitor-vm1",
                cpu=1,
                memory_mib=1024,
                disk_gib=20,
                status=InstanceStatusEnum.CREATING_PENDING,
                ip_address=None,
                host_node="localhost",
                reserve_resources=True,
                last_task_id=None,
                deleted_at=None,
                created_at=stale_time,
                updated_at=stale_time,
            )
        )
        session.add(
            InstanceTaskModel(
                id=task_id,
                instance_id=instance_id,
                command=TaskCommandEnum.CREATE,
                status=TaskStatusEnum.QUEUED,
                request_id=request_id,
                request_payload={"host_node": "localhost"},
                result_payload=None,
                error_code=None,
                error_message=None,
                retry_of_task_id=None,
                canceled_by=None,
                cancel_reason=None,
                attempt_count=0,
                max_attempts=3,
                created_at=stale_time,
                started_at=None,
                finished_at=None,
                updated_at=stale_time,
            )
        )
        session.add(
            CommandOutboxModel(
                id=outbox_id,
                topic="instance.create",
                task_id=task_id,
                request_id=request_id,
                payload={"instance_id": str(instance_id), "host_node": "localhost"},
                status=OutboxStatusEnum.QUEUED,
                attempt_count=0,
                max_attempts=3,
                next_attempt_at=stale_time,
                locked_by=None,
                lock_expires_at=None,
                last_error=None,
                sent_at=None,
                created_at=stale_time,
                updated_at=stale_time,
            )
        )
        await session.commit()

    monitor = StaleTaskMonitor(
        session_factory=session_factory,
        queued_timeout_seconds=1,
        sweep_interval_seconds=10,
    )
    await asyncio.sleep(1.2)
    recovered = await monitor._sweep_once()
    assert recovered == 0

    async with session_factory() as session:
        await session.execute(
            update(CommandOutboxModel)
            .where(CommandOutboxModel.id == outbox_id)
            .values(status=OutboxStatusEnum.FAILED, last_error="publish failed")
        )
        await session.commit()

    recovered = await monitor._sweep_once()
    assert recovered == 1

    async with session_factory() as session:
        task = await session.scalar(
            select(InstanceTaskModel).where(InstanceTaskModel.id == task_id)
        )
    assert task is not None
    assert _enum_value(task.status) == "failed"
    assert task.error_code == "TIMEOUT"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_handler_rejects_when_active_task_exists(session_factory):
    provisioning = DummyProvisioning()

    async with session_factory() as session:
        create_handler = CreateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            outbox_repository=provisioning,
            accounting=HostResourceAccountingAdapter(session),
        )
        accepted = await create_handler.handle(
            CreateInstanceCommand(
                cpu=1,
                memory_mib=1024,
                disk_gib=20,
                name="integration-vm-conflict",
                host_node="localhost",
            )
        )
        await session.commit()

    async with session_factory() as session:
        update_handler = UpdateInstanceHandler(
            write_repository=PostgresInstanceRepository(session),
            task_repository=PostgresTaskRepository(session),
            outbox_repository=provisioning,
            accounting=HostResourceAccountingAdapter(session),
        )
        with pytest.raises(ConflictError):
            await update_handler.handle(
                UpdateInstanceCommand(
                    instance_id=accepted.instance_id,
                    cpu=2,
                    memory_mib=2048,
                    disk_gib=30,
                    host_node="localhost",
                )
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_token_repository_create_and_revoke(session_factory):
    async with session_factory() as session:
        users = PostgresUserRepository(session)
        refresh_tokens = PostgresRefreshTokenRepository(session)
        user = await users.ensure_user(
            username="integration-auth-user",
            password_hash=hash_password("integration-pass"),
            role="viewer",
            tenant_id=UUID(DEFAULT_TENANT_ID),
        )
        token_hash = "abc123hash"
        created = await refresh_tokens.create(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        active = await refresh_tokens.get_active_by_hash(token_hash)
        revoked = await refresh_tokens.revoke_by_hash(token_hash)
        await session.commit()

    assert created.token_hash == token_hash
    assert active is not None
    assert active.user_id == user.id
    assert revoked is not None
    assert revoked.revoked_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_repository_create_list_update_and_count_admins(session_factory):
    async with session_factory() as session:
        users = PostgresUserRepository(session)
        created = await users.create_user(
            username="integration-user-mgmt",
            password_hash=hash_password("integration-pass-2"),
            role="operator",
            is_active=True,
            tenant_id=UUID(DEFAULT_TENANT_ID),
        )
        listed, total = await users.list_users(
            limit=50,
            offset=0,
            role=None,
            is_active=True,
            username="integration-user-mgmt",
        )
        updated = await users.update_user(
            user_id=created.id,
            role="admin",
            is_active=True,
            password_hash=None,
        )
        active_admins = await users.count_active_admins()
        await session.commit()

    assert created.role == "operator"
    assert total >= 1
    assert any(item.id == created.id for item in listed)
    assert updated.role == "admin"
    assert active_admins >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_token_repository_revoke_all_for_user(session_factory):
    async with session_factory() as session:
        users = PostgresUserRepository(session)
        refresh_tokens = PostgresRefreshTokenRepository(session)
        user = await users.ensure_user(
            username="integration-auth-user-revoke-all",
            password_hash=hash_password("integration-pass-3"),
            role="viewer",
            tenant_id=UUID(DEFAULT_TENANT_ID),
        )
        await refresh_tokens.create(
            user_id=user.id,
            token_hash="hash-revoke-all-1",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        await refresh_tokens.create(
            user_id=user.id,
            token_hash="hash-revoke-all-2",
            expires_at=datetime(2099, 1, 2, tzinfo=timezone.utc),
        )
        revoked_count = await refresh_tokens.revoke_all_for_user(user.id)
        still_active_1 = await refresh_tokens.get_active_by_hash("hash-revoke-all-1")
        still_active_2 = await refresh_tokens.get_active_by_hash("hash-revoke-all-2")
        await session.commit()

    assert revoked_count >= 2
    assert still_active_1 is None
    assert still_active_2 is None
