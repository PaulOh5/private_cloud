from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

import pytest

import app.adapters.rabbitmq_result_consumer as consumer_module
from app.application.services.task_result_processor import RetryableResultEventError


@dataclass
class _Method:
    delivery_tag: int


class _DummySession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        return None


class _DummySessionFactory:
    def __call__(self):
        return _DummySession()


class _FakeChannel:
    def __init__(self, stop_event, body: bytes):
        self.stop_event = stop_event
        self.body = body
        self.acks: list[int] = []
        self.nacks: list[tuple[int, bool]] = []
        self.is_open = True

    def exchange_declare(self, **_kwargs):
        return None

    def queue_declare(self, **_kwargs):
        return None

    def queue_bind(self, **_kwargs):
        return None

    def consume(self, _queue, inactivity_timeout=1, auto_ack=False):
        yield _Method(delivery_tag=1), None, self.body
        while not self.stop_event.is_set():
            yield None, None, None

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)
        self.stop_event.set()

    def basic_nack(self, delivery_tag, requeue):
        self.nacks.append((delivery_tag, requeue))
        self.stop_event.set()

    def close(self):
        self.is_open = False


class _FakeConnection:
    def __init__(self, channel: _FakeChannel):
        self._channel = channel
        self.is_open = True

    def channel(self):
        return self._channel

    def close(self):
        self.is_open = False


def _valid_event_body() -> bytes:
    payload = {
        "task_id": str(uuid4()),
        "request_id": str(uuid4()),
        "instance_id": str(uuid4()),
        "command": "create",
        "status": "running",
        "attempt_count": 1,
        "timestamp": "2026-01-01T00:00:00Z",
    }
    return json.dumps(payload).encode("utf-8")


def test_result_consumer_retryable_error_nacks_with_requeue(monkeypatch):
    class _RetryProcessor:
        def __init__(self, *_args, **_kwargs):
            pass

        def process(self, _event):
            raise RetryableResultEventError("temporary")

    monkeypatch.setattr(consumer_module, "TaskResultProcessor", _RetryProcessor)

    consumer = consumer_module.RabbitMqVmResultConsumer("amqp://unused", _DummySessionFactory())
    fake_channel = _FakeChannel(consumer._stop_event, _valid_event_body())
    monkeypatch.setattr(consumer, "_connection", lambda: _FakeConnection(fake_channel))
    monkeypatch.setattr(consumer, "_declare", lambda _channel: None)

    consumer._run()
    assert fake_channel.acks == []
    assert fake_channel.nacks == [(1, True)]


def test_result_consumer_nonretryable_payload_nacks_without_requeue(monkeypatch):
    consumer = consumer_module.RabbitMqVmResultConsumer("amqp://unused", _DummySessionFactory())
    fake_channel = _FakeChannel(consumer._stop_event, b"{not-json")
    monkeypatch.setattr(consumer, "_connection", lambda: _FakeConnection(fake_channel))
    monkeypatch.setattr(consumer, "_declare", lambda _channel: None)

    consumer._run()
    assert fake_channel.acks == []
    assert fake_channel.nacks == [(1, False)]


def test_result_consumer_marks_ready_after_topology_declare(monkeypatch):
    class _NoopProcessor:
        def __init__(self, *_args, **_kwargs):
            pass

        def process(self, _event):
            return None

    monkeypatch.setattr(consumer_module, "TaskResultProcessor", _NoopProcessor)

    consumer = consumer_module.RabbitMqVmResultConsumer("amqp://unused", _DummySessionFactory())
    fake_channel = _FakeChannel(consumer._stop_event, _valid_event_body())
    monkeypatch.setattr(consumer, "_connection", lambda: _FakeConnection(fake_channel))
    monkeypatch.setattr(consumer, "_declare", lambda _channel: None)

    consumer._run()
    assert consumer.wait_until_ready(timeout=0) is True
