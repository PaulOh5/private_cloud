from __future__ import annotations

import importlib
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings

postgres = pytest.importorskip("testcontainers.postgres")
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class DummyVmProvisioningAdapter:
    def __init__(self, *_args, **_kwargs):
        pass

    def publish_command(self, *_args, **_kwargs):
        return None


class DummyVmResultConsumer:
    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        return None

    def stop(self):
        return None


class DummyVmImageSyncRpcAdapter:
    def __init__(self, *_args, **_kwargs):
        pass

    def sync_images(self):
        return {
            "status": "synced",
            "default_image_id": "ubuntu-24.04",
            "total_images": 1,
            "synchronized_items": [{"id": "ubuntu-24.04", "path": "/var/lib/vm-manager/images/ubuntu-24.04/base.qcow2"}],
        }


@pytest.fixture(scope="module")
def pg_container():
    with postgres.PostgresContainer("postgres:16") as c:
        yield c


@pytest.fixture
def api_client(pg_container, monkeypatch):
    parsed = urlparse(pg_container.get_connection_url(driver=None))
    monkeypatch.setenv("POSTGRES_USER", parsed.username or "test")
    monkeypatch.setenv("POSTGRES_PASSWORD", parsed.password or "test")
    monkeypatch.setenv("POSTGRES_DB", parsed.path.lstrip("/") or "test")
    monkeypatch.setenv("POSTGRES_HOST", parsed.hostname or "localhost")
    monkeypatch.setenv("POSTGRES_PORT", str(parsed.port or 5432))
    monkeypatch.setenv("AUTH_JWT_SECRET", "integration-secret")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin1234")
    monkeypatch.setenv("OUTBOX_RELAY_ENABLED", "false")

    import app.runtime.workers.rabbitmq_result_consumer as result_module
    import app.adapters.rabbitmq_rpc as rpc_module
    import app.adapters.rabbitmq_image_sync_rpc as image_sync_module

    monkeypatch.setattr(rpc_module, "RabbitMqVmProvisioningAdapter", DummyVmProvisioningAdapter)
    monkeypatch.setattr(result_module, "RabbitMqVmResultConsumer", DummyVmResultConsumer)
    monkeypatch.setattr(image_sync_module, "RabbitMqVmImageSyncRpcAdapter", DummyVmImageSyncRpcAdapter)

    get_settings.cache_clear()
    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
def test_roles_endpoint_and_admin_login(api_client: TestClient):
    tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    roles = api_client.get("/roles", headers=headers)
    assert roles.status_code == 200
    role_names = {item["name"] for item in roles.json()["items"]}
    assert role_names == {"admin", "operator", "viewer"}


@pytest.mark.integration
def test_images_endpoint_returns_catalog(api_client: TestClient):
    tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = api_client.get("/images", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"]
    assert any(item["id"] == "ubuntu-24.04" and item["is_default"] for item in payload["items"])


@pytest.mark.integration
def test_images_sync_endpoint_returns_sync_result(api_client: TestClient):
    tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = api_client.post("/images/sync", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "synced"
    assert payload["default_image_id"] == "ubuntu-24.04"
    assert payload["total_images"] == 1
    assert payload["synchronized_items"]


@pytest.mark.integration
def test_user_management_and_rbac(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    username = f"operator-{uuid4().hex[:8]}"
    password = "operator-password-1"
    create_resp = api_client.post(
        "/users",
        headers=admin_headers,
        json={
            "username": username,
            "password": password,
            "role": "operator",
            "tenant_id": DEFAULT_TENANT_ID,
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    user_id = create_resp.json()["id"]

    operator_tokens = _login(api_client, username, password)
    operator_headers = {"Authorization": f"Bearer {operator_tokens['access_token']}"}

    denied = api_client.get("/users", headers=operator_headers)
    assert denied.status_code == 403

    self_info = api_client.get(f"/users/{user_id}", headers=operator_headers)
    assert self_info.status_code == 200
    assert self_info.json()["username"] == username


@pytest.mark.integration
def test_refresh_token_revoked_after_admin_user_update(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    username = f"viewer-{uuid4().hex[:8]}"
    password = "viewer-password-1"
    create_resp = api_client.post(
        "/users",
        headers=admin_headers,
        json={
            "username": username,
            "password": password,
            "role": "viewer",
            "tenant_id": DEFAULT_TENANT_ID,
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    user_id = create_resp.json()["id"]

    viewer_tokens = _login(api_client, username, password)
    refresh_token = viewer_tokens["refresh_token"]

    update_resp = api_client.patch(
        f"/users/{user_id}",
        headers=admin_headers,
        json={"role": "operator"},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["role"] == "operator"

    refresh_resp = api_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 401


@pytest.mark.integration
def test_cannot_deactivate_self_or_last_admin(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    me = api_client.get("/auth/me", headers=admin_headers)
    assert me.status_code == 200
    admin_id = me.json()["id"]

    deactivate_self = api_client.delete(f"/users/{admin_id}", headers=admin_headers)
    assert deactivate_self.status_code == 409

    demote_last_admin = api_client.patch(
        f"/users/{admin_id}",
        headers=admin_headers,
        json={"role": "viewer", "tenant_id": DEFAULT_TENANT_ID},
    )
    assert demote_last_admin.status_code == 409


@pytest.mark.integration
def test_audit_logs_admin_only_and_contains_user_create_event(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    username = f"audit-user-{uuid4().hex[:8]}"
    create_resp = api_client.post(
        "/users",
        headers=admin_headers,
        json={
            "username": username,
            "password": "audit-password-1",
            "role": "viewer",
            "tenant_id": DEFAULT_TENANT_ID,
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created_user_id = create_resp.json()["id"]

    operator_tokens = _login(api_client, username, "audit-password-1")
    operator_headers = {"Authorization": f"Bearer {operator_tokens['access_token']}"}

    denied = api_client.get("/audit-logs", headers=operator_headers)
    assert denied.status_code == 403

    logs = api_client.get(
        "/audit-logs",
        headers=admin_headers,
        params={"action": "user.create", "target_type": "user"},
    )
    assert logs.status_code == 200, logs.text
    items = logs.json()["items"]
    assert any(item["target_id"] == created_user_id for item in items)


@pytest.mark.integration
def test_failed_login_writes_audit_log(api_client: TestClient):
    wrong_username = f"missing-{uuid4().hex[:8]}"
    failed = api_client.post("/auth/login", json={"username": wrong_username, "password": "wrong-password"})
    assert failed.status_code == 401

    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    logs = api_client.get(
        "/audit-logs",
        headers=admin_headers,
        params={"action": "auth.login.failed", "target_type": "user"},
    )
    assert logs.status_code == 200, logs.text
    items = logs.json()["items"]
    assert any(item["actor_username"] == wrong_username for item in items)


@pytest.mark.integration
def test_retry_api_returns_202_and_creates_new_task(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    create_resp = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": DEFAULT_TENANT_ID, "name": "retry-api-vm", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert create_resp.status_code == 202, create_resp.text
    original_task_id = create_resp.json()["task_id"]
    instance_id = create_resp.json()["instance_id"]

    with api_client.app.state.session_factory() as session:
        session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'failed',
                    error_code = 'QEMU_ERROR',
                    error_message = 'forced failure',
                    finished_at = :now,
                    updated_at = :now
                WHERE id = :task_id
                """
            ),
            {"task_id": original_task_id, "now": datetime.now(timezone.utc)},
        )
        session.execute(
            text(
                """
                UPDATE instances
                SET status = 'error',
                    reserve_resources = false,
                    last_task_id = NULL,
                    ip_address = NULL,
                    updated_at = :now
                WHERE id = :instance_id
                """
            ),
            {"instance_id": instance_id, "now": datetime.now(timezone.utc)},
        )
        session.commit()

    retry_resp = api_client.post(f"/tasks/{original_task_id}/retry", headers=headers)
    assert retry_resp.status_code == 202, retry_resp.text
    payload = retry_resp.json()
    assert payload["status"] == "queued"
    assert payload["task_id"] != original_task_id

    with api_client.app.state.session_factory() as session:
        row = session.execute(
            text("SELECT status, retry_of_task_id FROM instance_tasks WHERE id = :id"),
            {"id": payload["task_id"]},
        ).mappings().one()
    assert row["status"] == "queued"
    assert str(row["retry_of_task_id"]) == original_task_id


@pytest.mark.integration
def test_cancel_queued_task_sets_terminal_canceled(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    create_resp = api_client.post(
        "/instances",
        headers=headers,
        json={
            "tenant_id": DEFAULT_TENANT_ID,
            "name": "cancel-queued-vm",
            "cpu": 1,
            "memory_mib": 1024,
            "disk_gib": 20,
        },
    )
    assert create_resp.status_code == 202, create_resp.text
    task_id = create_resp.json()["task_id"]

    cancel_resp = api_client.post(
        f"/tasks/{task_id}/cancel",
        headers=headers,
        json={"reason": "operator request"},
    )
    assert cancel_resp.status_code == 202, cancel_resp.text
    assert cancel_resp.json()["status"] == "canceled"

    task_resp = api_client.get(f"/tasks/{task_id}", headers=headers)
    assert task_resp.status_code == 200
    assert task_resp.json()["status"] == "canceled"


@pytest.mark.integration
def test_cancel_running_task_sets_cancel_pending(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    create_resp = api_client.post(
        "/instances",
        headers=headers,
        json={
            "tenant_id": DEFAULT_TENANT_ID,
            "name": "cancel-running-vm",
            "cpu": 1,
            "memory_mib": 1024,
            "disk_gib": 20,
        },
    )
    assert create_resp.status_code == 202, create_resp.text
    task_id = create_resp.json()["task_id"]

    with api_client.app.state.session_factory() as session:
        session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'running',
                    started_at = :now,
                    updated_at = :now
                WHERE id = :task_id
                """
            ),
            {"task_id": task_id, "now": datetime.now(timezone.utc)},
        )
        session.commit()

    cancel_resp = api_client.post(
        f"/tasks/{task_id}/cancel",
        headers=headers,
        json={"reason": "long running"},
    )
    assert cancel_resp.status_code == 202, cancel_resp.text
    assert cancel_resp.json()["status"] == "cancel_pending"

    task_resp = api_client.get(f"/tasks/{task_id}", headers=headers)
    assert task_resp.status_code == 200
    assert task_resp.json()["status"] == "cancel_pending"


@pytest.mark.integration
def test_retry_cancel_audit_logs_are_written(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    create_resp = api_client.post(
        "/instances",
        headers=headers,
        json={
            "tenant_id": DEFAULT_TENANT_ID,
            "name": "audit-retry-vm",
            "cpu": 1,
            "memory_mib": 1024,
            "disk_gib": 20,
        },
    )
    assert create_resp.status_code == 202, create_resp.text
    original_task_id = create_resp.json()["task_id"]
    instance_id = create_resp.json()["instance_id"]

    with api_client.app.state.session_factory() as session:
        now = datetime.now(timezone.utc)
        session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'failed',
                    error_code = 'QEMU_ERROR',
                    error_message = 'forced failure',
                    finished_at = :now,
                    updated_at = :now
                WHERE id = :task_id
                """
            ),
            {"task_id": original_task_id, "now": now},
        )
        session.execute(
            text(
                """
                UPDATE instances
                SET status = 'error',
                    reserve_resources = false,
                    last_task_id = NULL,
                    ip_address = NULL,
                    updated_at = :now
                WHERE id = :instance_id
                """
            ),
            {"instance_id": instance_id, "now": now},
        )
        session.commit()

    retry_resp = api_client.post(f"/tasks/{original_task_id}/retry", headers=headers)
    assert retry_resp.status_code == 202, retry_resp.text

    cancel_task_id = retry_resp.json()["task_id"]
    with api_client.app.state.session_factory() as session:
        session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'queued',
                    updated_at = :now
                WHERE id = :task_id
                """
            ),
            {"task_id": cancel_task_id, "now": datetime.now(timezone.utc)},
        )
        session.commit()

    cancel_resp = api_client.post(f"/tasks/{cancel_task_id}/cancel", headers=headers, json={"reason": "audit"})
    assert cancel_resp.status_code == 202, cancel_resp.text
    assert cancel_resp.json()["status"] == "canceled"

    retry_logs = api_client.get(
        "/audit-logs",
        headers=headers,
        params={"action": "task.retry.requested", "target_type": "task"},
    )
    assert retry_logs.status_code == 200, retry_logs.text
    assert any(item["target_id"] == original_task_id for item in retry_logs.json()["items"])

    cancel_logs = api_client.get(
        "/audit-logs",
        headers=headers,
        params={"action": "task.cancel.requested", "target_type": "task"},
    )
    assert cancel_logs.status_code == 200, cancel_logs.text
    assert any(item["target_id"] == cancel_task_id for item in cancel_logs.json()["items"])


@pytest.mark.integration
def test_stop_start_endpoints_create_tasks_and_audit_logs(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    create_resp = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": DEFAULT_TENANT_ID, "name": "stop-start-vm", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert create_resp.status_code == 202, create_resp.text
    create_task_id = create_resp.json()["task_id"]
    instance_id = create_resp.json()["instance_id"]

    with api_client.app.state.session_factory() as session:
        now = datetime.now(timezone.utc)
        session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'succeeded',
                    finished_at = :now,
                    updated_at = :now
                WHERE id = :task_id
                """
            ),
            {"task_id": create_task_id, "now": now},
        )
        session.execute(
            text(
                """
                UPDATE instances
                SET status = 'running',
                    reserve_resources = true,
                    updated_at = :now
                WHERE id = :instance_id
                """
            ),
            {"instance_id": instance_id, "now": now},
        )
        session.commit()

    stop_resp = api_client.post(f"/instances/{instance_id}/stop", headers=headers)
    assert stop_resp.status_code == 202, stop_resp.text
    assert stop_resp.json()["command"] == "stop"
    stop_task_id = stop_resp.json()["task_id"]

    with api_client.app.state.session_factory() as session:
        now = datetime.now(timezone.utc)
        session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'succeeded',
                    finished_at = :now,
                    updated_at = :now
                WHERE id = :task_id
                """
            ),
            {"task_id": stop_task_id, "now": now},
        )
        session.execute(
            text(
                """
                UPDATE instances
                SET status = 'stopped',
                    reserve_resources = true,
                    updated_at = :now
                WHERE id = :instance_id
                """
            ),
            {"instance_id": instance_id, "now": now},
        )
        session.commit()

    start_resp = api_client.post(f"/instances/{instance_id}/start", headers=headers)
    assert start_resp.status_code == 202, start_resp.text
    assert start_resp.json()["command"] == "start"

    stop_logs = api_client.get(
        "/audit-logs",
        headers=headers,
        params={"action": "instance.stop.requested", "target_type": "instance"},
    )
    assert stop_logs.status_code == 200, stop_logs.text
    assert any(item["target_id"] == instance_id for item in stop_logs.json()["items"])

    start_logs = api_client.get(
        "/audit-logs",
        headers=headers,
        params={"action": "instance.start.requested", "target_type": "instance"},
    )
    assert start_logs.status_code == 200, start_logs.text
    assert any(item["target_id"] == instance_id for item in start_logs.json()["items"])


@pytest.mark.integration
def test_start_from_stopped_fails_when_tenant_quota_exceeded(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    tenant_key = f"tenant-start-quota-{uuid4().hex[:8]}"
    create_tenant = api_client.post(
        "/tenants",
        headers=headers,
        json={
            "key": tenant_key,
            "name": "Start Quota Tenant",
            "is_active": True,
            "max_instances": 2,
            "max_cpu": 2,
            "max_memory_mib": 4096,
            "max_disk_gib": 100,
        },
    )
    assert create_tenant.status_code == 201, create_tenant.text
    tenant_id = create_tenant.json()["id"]

    vm1_resp = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": tenant_id, "name": "quota-run", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert vm1_resp.status_code == 202, vm1_resp.text
    vm1_id = vm1_resp.json()["instance_id"]
    vm1_task = vm1_resp.json()["task_id"]

    vm2_resp = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": tenant_id, "name": "quota-stop", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert vm2_resp.status_code == 202, vm2_resp.text
    vm2_id = vm2_resp.json()["instance_id"]
    vm2_task = vm2_resp.json()["task_id"]

    with api_client.app.state.session_factory() as session:
        now = datetime.now(timezone.utc)
        session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'succeeded',
                    finished_at = :now,
                    updated_at = :now
                WHERE id IN (:task1, :task2)
                """
            ),
            {"task1": vm1_task, "task2": vm2_task, "now": now},
        )
        session.execute(
            text(
                """
                UPDATE instances
                SET status = CASE
                    WHEN id = :vm1_id THEN 'running'
                    WHEN id = :vm2_id THEN 'stopped'
                    ELSE status
                END,
                    reserve_resources = true,
                    updated_at = :now
                WHERE id IN (:vm1_id, :vm2_id)
                """
            ),
            {"vm1_id": vm1_id, "vm2_id": vm2_id, "now": now},
        )
        session.commit()

    reduce_quota = api_client.patch(
        f"/tenants/{tenant_id}/quota",
        headers=headers,
        json={
            "max_instances": 2,
            "max_cpu": 1,
            "max_memory_mib": 4096,
            "max_disk_gib": 100,
        },
    )
    assert reduce_quota.status_code == 200, reduce_quota.text

    start_resp = api_client.post(f"/instances/{vm2_id}/start", headers=headers)
    assert start_resp.status_code == 409, start_resp.text
    assert start_resp.json()["code"] == "QUOTA_EXCEEDED"


@pytest.mark.integration
def test_start_from_stopped_fails_when_host_capacity_exceeded(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    vm1_resp = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": DEFAULT_TENANT_ID, "name": "cap-run", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert vm1_resp.status_code == 202, vm1_resp.text
    vm1_id = vm1_resp.json()["instance_id"]
    vm1_task = vm1_resp.json()["task_id"]

    vm2_resp = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": DEFAULT_TENANT_ID, "name": "cap-stop", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert vm2_resp.status_code == 202, vm2_resp.text
    vm2_id = vm2_resp.json()["instance_id"]
    vm2_task = vm2_resp.json()["task_id"]

    with api_client.app.state.session_factory() as session:
        now = datetime.now(timezone.utc)
        session.execute(
            text(
                """
                UPDATE instance_tasks
                SET status = 'succeeded',
                    finished_at = :now,
                    updated_at = :now
                WHERE id IN (:task1, :task2)
                """
            ),
            {"task1": vm1_task, "task2": vm2_task, "now": now},
        )
        session.execute(
            text(
                """
                UPDATE instances
                SET status = CASE
                    WHEN id = :vm1_id THEN 'running'
                    WHEN id = :vm2_id THEN 'stopped'
                    ELSE status
                END,
                    reserve_resources = true,
                    updated_at = :now
                WHERE id IN (:vm1_id, :vm2_id)
                """
            ),
            {"vm1_id": vm1_id, "vm2_id": vm2_id, "now": now},
        )
        session.execute(
            text(
                """
                UPDATE resource_capacity
                SET total_cpu = 1,
                    total_memory_mib = 2048,
                    total_disk_gib = 5000
                WHERE host_node = 'localhost'
                """
            )
        )
        session.commit()

    start_resp = api_client.post(f"/instances/{vm2_id}/start", headers=headers)
    assert start_resp.status_code == 409, start_resp.text
    assert start_resp.json()["code"] == "CAPACITY_EXCEEDED"
