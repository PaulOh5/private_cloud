from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.adapters.console_ticket_store import ConsoleTicketStore
from app.application.services.console_port import compute_console_vnc_port


def test_console_port_is_deterministic():
    instance_id = "123e4567-e89b-12d3-a456-426614174000"
    first = compute_console_vnc_port(instance_id, base=20000, span=40000)
    second = compute_console_vnc_port(instance_id, base=20000, span=40000)
    assert first == second
    assert 20000 <= first < 60000


def test_console_ticket_is_single_use():
    store = ConsoleTicketStore()
    instance_id = uuid4()
    user_id = uuid4()

    record = store.issue(instance_id=instance_id, issued_by_user_id=user_id, ttl_seconds=300)
    first_consume = store.consume(ticket=record.ticket, instance_id=instance_id)
    second_consume = store.consume(ticket=record.ticket, instance_id=instance_id)

    assert first_consume is not None
    assert second_consume is None


def test_console_ticket_rejects_expired_ticket():
    store = ConsoleTicketStore()
    instance_id = uuid4()
    user_id = uuid4()

    record = store.issue(instance_id=instance_id, issued_by_user_id=user_id, ttl_seconds=1)
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert store.consume(ticket=record.ticket, instance_id=instance_id) is None
