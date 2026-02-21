from __future__ import annotations

import importlib
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
            "synchronized_items": [{"id": "ubuntu-24.04", "path": "/tmp/base.qcow2"}],
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

    import app.adapters.rabbitmq_result_consumer as result_module
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
def test_default_tenant_is_bootstrapped(api_client: TestClient):
    admin = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    response = api_client.get("/tenants", headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert any(item["id"] == DEFAULT_TENANT_ID and item["key"] == "default" for item in items)


@pytest.mark.integration
def test_create_instance_enqueues_command_outbox(api_client: TestClient):
    admin = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    created = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": DEFAULT_TENANT_ID, "name": "outbox-api", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]

    with api_client.app.state.session_factory() as session:
        row = session.execute(
            text(
                """
                SELECT topic, status
                FROM command_outbox
                WHERE task_id = :task_id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        ).mappings().one()

    assert row["topic"] == "instance.create"
    assert row["status"] in {"queued", "sent"}


@pytest.mark.integration
def test_admin_instance_requires_tenant_id_and_enforces_quota(api_client: TestClient):
    admin = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    tenant_key = f"tenant-{uuid4().hex[:8]}"
    create_tenant = api_client.post(
        "/tenants",
        headers=headers,
        json={
            "key": tenant_key,
            "name": "Tenant A",
            "is_active": True,
            "max_instances": 1,
            "max_cpu": 2,
            "max_memory_mib": 4096,
            "max_disk_gib": 50,
        },
    )
    assert create_tenant.status_code == 201, create_tenant.text
    tenant_id = create_tenant.json()["id"]

    missing_tenant = api_client.post(
        "/instances",
        headers=headers,
        json={"name": "vm-no-tenant", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert missing_tenant.status_code == 400

    first = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": tenant_id, "name": "vm-1", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert first.status_code == 202, first.text

    second = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": tenant_id, "name": "vm-2", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "QUOTA_EXCEEDED"


@pytest.mark.integration
def test_tenant_quota_reduction_below_usage_is_blocked(api_client: TestClient):
    admin = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    tenant_key = f"tenant-{uuid4().hex[:8]}"
    create_tenant = api_client.post(
        "/tenants",
        headers=headers,
        json={
            "key": tenant_key,
            "name": "Tenant B",
            "is_active": True,
            "max_instances": 5,
            "max_cpu": 8,
            "max_memory_mib": 16384,
            "max_disk_gib": 200,
        },
    )
    assert create_tenant.status_code == 201, create_tenant.text
    tenant_id = create_tenant.json()["id"]

    created = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": tenant_id, "name": "vm-usage", "cpu": 2, "memory_mib": 2048, "disk_gib": 30},
    )
    assert created.status_code == 202, created.text

    reduce = api_client.patch(
        f"/tenants/{tenant_id}/quota",
        headers=headers,
        json={
            "max_instances": 5,
            "max_cpu": 1,
            "max_memory_mib": 16384,
            "max_disk_gib": 200,
        },
    )
    assert reduce.status_code == 409, reduce.text
    assert reduce.json()["code"] == "QUOTA_CONFLICT"


@pytest.mark.integration
def test_non_admin_cross_tenant_instance_access_returns_404(api_client: TestClient):
    admin = _login(api_client, "admin", "admin1234")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    tenant_a = api_client.post(
        "/tenants",
        headers=headers,
        json={
            "key": f"tenant-{uuid4().hex[:8]}",
            "name": "Tenant C",
            "is_active": True,
            "max_instances": 5,
            "max_cpu": 8,
            "max_memory_mib": 16384,
            "max_disk_gib": 200,
        },
    )
    assert tenant_a.status_code == 201, tenant_a.text
    tenant_a_id = tenant_a.json()["id"]

    tenant_b = api_client.post(
        "/tenants",
        headers=headers,
        json={
            "key": f"tenant-{uuid4().hex[:8]}",
            "name": "Tenant D",
            "is_active": True,
            "max_instances": 5,
            "max_cpu": 8,
            "max_memory_mib": 16384,
            "max_disk_gib": 200,
        },
    )
    assert tenant_b.status_code == 201, tenant_b.text
    tenant_b_id = tenant_b.json()["id"]

    create_user = api_client.post(
        "/users",
        headers=headers,
        json={
            "username": f"operator-{uuid4().hex[:8]}",
            "password": "operator-password-1",
            "role": "operator",
            "tenant_id": tenant_a_id,
            "is_active": True,
        },
    )
    assert create_user.status_code == 201, create_user.text
    username = create_user.json()["username"]

    create_vm = api_client.post(
        "/instances",
        headers=headers,
        json={"tenant_id": tenant_b_id, "name": "vm-b", "cpu": 1, "memory_mib": 1024, "disk_gib": 20},
    )
    assert create_vm.status_code == 202, create_vm.text
    instance_id = create_vm.json()["instance_id"]

    operator = _login(api_client, username, "operator-password-1")
    operator_headers = {"Authorization": f"Bearer {operator['access_token']}"}

    denied = api_client.get(f"/instances/{instance_id}", headers=operator_headers)
    assert denied.status_code == 404
