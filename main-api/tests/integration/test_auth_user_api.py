from __future__ import annotations

import importlib
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

postgres = pytest.importorskip("testcontainers.postgres")


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

    import app.adapters.rabbitmq_result_consumer as result_module
    import app.adapters.rabbitmq_rpc as rpc_module

    monkeypatch.setattr(rpc_module, "RabbitMqVmProvisioningAdapter", DummyVmProvisioningAdapter)
    monkeypatch.setattr(result_module, "RabbitMqVmResultConsumer", DummyVmResultConsumer)

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
def test_user_management_and_rbac(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    username = f"operator-{uuid4().hex[:8]}"
    password = "operator-password-1"
    create_resp = api_client.post(
        "/users",
        headers=admin_headers,
        json={"username": username, "password": password, "role": "operator", "is_active": True},
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
        json={"username": username, "password": password, "role": "viewer", "is_active": True},
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

    demote_last_admin = api_client.patch(f"/users/{admin_id}", headers=admin_headers, json={"role": "viewer"})
    assert demote_last_admin.status_code == 409


@pytest.mark.integration
def test_audit_logs_admin_only_and_contains_user_create_event(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    username = f"audit-user-{uuid4().hex[:8]}"
    create_resp = api_client.post(
        "/users",
        headers=admin_headers,
        json={"username": username, "password": "audit-password-1", "role": "viewer", "is_active": True},
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
