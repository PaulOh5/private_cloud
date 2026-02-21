from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import pika

from app.infra.messaging.rabbitmq import (
    COMMAND_EXCHANGE,
    COMMAND_QUEUE,
    DEAD_LETTER_EXCHANGE,
    DEAD_LETTER_QUEUE,
    open_blocking_connection,
    setup_vm_command_topology,
)
from app.ports import VmImageSyncError, VmImageSyncPort


class VmImageSyncRpcError(VmImageSyncError):
    pass


class RabbitMqVmImageSyncRpcAdapter(VmImageSyncPort):
    COMMAND_EXCHANGE = COMMAND_EXCHANGE
    COMMAND_QUEUE = COMMAND_QUEUE
    DEAD_LETTER_EXCHANGE = DEAD_LETTER_EXCHANGE
    DEAD_LETTER_QUEUE = DEAD_LETTER_QUEUE
    _ROUTING_KEYS = ("image.sync",)

    def __init__(self, amqp_url: str, timeout_seconds: int):
        self.amqp_url = amqp_url
        self.timeout_seconds = max(int(timeout_seconds), 1)
        self._setup_topology()

    def _connection(self):
        return open_blocking_connection(self.amqp_url)

    def _setup_topology(self) -> None:
        connection = self._connection()
        channel = connection.channel()
        try:
            setup_vm_command_topology(channel, routing_keys=self._ROUTING_KEYS)
        finally:
            channel.close()
            connection.close()

    def sync_images(self) -> dict:
        connection = self._connection()
        channel = connection.channel()
        try:
            callback_queue = channel.queue_declare(queue="", exclusive=True, auto_delete=True).method.queue
            correlation_id = str(uuid4())
            message = {
                "task_id": str(uuid4()),
                "request_id": str(uuid4()),
                "instance_id": str(uuid4()),
                "command": "image.sync",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {},
                "correlation_id": correlation_id,
            }
            channel.basic_publish(
                exchange=self.COMMAND_EXCHANGE,
                routing_key="image.sync",
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    correlation_id=correlation_id,
                    reply_to=callback_queue,
                ),
                body=json.dumps(message).encode("utf-8"),
            )

            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                method, properties, body = channel.basic_get(queue=callback_queue, auto_ack=True)
                if method is None:
                    connection.process_data_events(time_limit=0.1)
                    time.sleep(0.1)
                    continue
                if properties and properties.correlation_id != correlation_id:
                    continue

                payload = json.loads(body.decode("utf-8"))
                if bool(payload.get("success")):
                    result = payload.get("result")
                    return result if isinstance(result, dict) else {}
                raise VmImageSyncRpcError(
                    code=str(payload.get("error_code") or "QEMU_ERROR"),
                    message=str(payload.get("error_message") or "image sync failed"),
                )

            raise VmImageSyncRpcError("TIMEOUT", "image sync command timed out")
        finally:
            try:
                channel.close()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass
