from __future__ import annotations

import importlib
import socket
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from starlette.websockets import WebSocketDisconnect

from app.adapters.postgres_repositories.orm.instance import InstanceModel
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
            "synchronized_items": [
                {
                    "id": "ubuntu-24.04",
                    "path": "/var/lib/vm-manager/images/ubuntu-24.04/base.qcow2",
                }
            ],
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

    monkeypatch.setattr(
        rpc_module, "RabbitMqVmProvisioningAdapter", DummyVmProvisioningAdapter
    )
    monkeypatch.setattr(
        result_module, "RabbitMqVmResultConsumer", DummyVmResultConsumer
    )
    monkeypatch.setattr(
        image_sync_module, "RabbitMqVmImageSyncRpcAdapter", DummyVmImageSyncRpcAdapter
    )

    get_settings.cache_clear()
    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_instance_status(
    client: TestClient, instance_id: str, status_value: str
) -> None:
    with client.app.state.session_factory() as session:
        session.execute(
            update(InstanceModel)
            .where(InstanceModel.id == UUID(instance_id))
            .values(status=status_value, updated_at=datetime.now(timezone.utc))
        )
        session.commit()


def _create_running_instance(client: TestClient, headers: dict[str, str]) -> str:
    create_response = client.post(
        "/instances",
        headers=headers,
        json={
            "tenant_id": DEFAULT_TENANT_ID,
            "name": "console-test",
            "cpu": 1,
            "memory_mib": 1024,
            "disk_gib": 20,
        },
    )
    assert create_response.status_code == 202, create_response.text
    instance_id = create_response.json()["instance_id"]
    _set_instance_status(client, instance_id, "running")
    return instance_id


@pytest.mark.integration
def test_console_ticket_issue_success_and_audit_log(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    instance_id = _create_running_instance(api_client, admin_headers)

    response = api_client.post(
        f"/instances/{instance_id}/console-ticket", headers=admin_headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ticket"]
    assert payload["websocket_path"].startswith(
        f"/instances/{instance_id}/console/ws?ticket="
    )

    logs = api_client.get(
        "/audit-logs",
        headers=admin_headers,
        params={"action": "instance.console.ticket_issued", "target_type": "instance"},
    )
    assert logs.status_code == 200, logs.text
    assert any(item["target_id"] == instance_id for item in logs.json()["items"])


@pytest.mark.integration
def test_console_ticket_forbidden_for_viewer(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

    username = f"viewer-{uuid4().hex[:8]}"
    password = "viewer-password-1"
    create_user = api_client.post(
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
    assert create_user.status_code == 201, create_user.text

    viewer_tokens = _login(api_client, username, password)
    viewer_headers = {"Authorization": f"Bearer {viewer_tokens['access_token']}"}
    instance_id = _create_running_instance(api_client, admin_headers)

    denied = api_client.post(
        f"/instances/{instance_id}/console-ticket", headers=viewer_headers
    )
    assert denied.status_code == 403


@pytest.mark.integration
def test_console_ticket_requires_running_status(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    instance_id = _create_running_instance(api_client, admin_headers)
    _set_instance_status(api_client, instance_id, "stopped")

    rejected = api_client.post(
        f"/instances/{instance_id}/console-ticket", headers=admin_headers
    )
    assert rejected.status_code == 409


@pytest.mark.integration
def test_console_websocket_proxy_allows_single_use_ticket(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    instance_id = _create_running_instance(api_client, admin_headers)

    response = api_client.post(
        f"/instances/{instance_id}/console-ticket", headers=admin_headers
    )
    assert response.status_code == 200, response.text
    ticket = response.json()["ticket"]

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()

    api_client.app.state.settings.console_proxy_host = "127.0.0.1"
    api_client.app.state.settings.console_vnc_port_base = port
    api_client.app.state.settings.console_vnc_port_span = 1

    server_ready = threading.Event()
    received: list[bytes] = []

    def fake_vnc_server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            server_ready.set()
            conn, _ = sock.accept()
            with conn:
                conn.sendall(b"RFB 003.008\n")
                received.append(conn.recv(32))

    server_thread = threading.Thread(target=fake_vnc_server, daemon=True)
    server_thread.start()
    assert server_ready.wait(timeout=2), "fake VNC server did not start in time"

    path = f"/instances/{instance_id}/console/ws?ticket={ticket}"
    with api_client.websocket_connect(path) as websocket:
        banner = websocket.receive_bytes()
        assert banner.startswith(b"RFB")
        websocket.send_bytes(b"ping")

    server_thread.join(timeout=2)
    assert received == [b"ping"]

    with pytest.raises(WebSocketDisconnect):
        with api_client.websocket_connect(path):
            pass


@pytest.mark.integration
def test_console_websocket_rejects_ticket_for_other_instance(api_client: TestClient):
    admin_tokens = _login(api_client, "admin", "admin1234")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    instance_a = _create_running_instance(api_client, admin_headers)
    instance_b = _create_running_instance(api_client, admin_headers)

    response = api_client.post(
        f"/instances/{instance_a}/console-ticket", headers=admin_headers
    )
    assert response.status_code == 200, response.text
    ticket = response.json()["ticket"]

    with pytest.raises(WebSocketDisconnect):
        with api_client.websocket_connect(
            f"/instances/{instance_b}/console/ws?ticket={ticket}"
        ):
            pass
