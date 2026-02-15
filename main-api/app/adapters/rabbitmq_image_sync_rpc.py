from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import pika


class VmImageSyncRpcError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RabbitMqVmImageSyncRpcAdapter:
    COMMAND_EXCHANGE = "vm.commands"
    COMMAND_QUEUE = "vm.commands.q"
    DEAD_LETTER_EXCHANGE = "vm.commands.dlx"
    DEAD_LETTER_QUEUE = "vm.commands.dlq"

    def __init__(self, amqp_url: str, timeout_seconds: int):
        self.amqp_url = amqp_url
        self.timeout_seconds = max(int(timeout_seconds), 1)
        self._setup_topology()

    def _connection(self):
        parameters = pika.URLParameters(self.amqp_url)
        parameters.heartbeat = 30
        parameters.blocked_connection_timeout = 30
        return pika.BlockingConnection(parameters)

    def _setup_topology(self) -> None:
        connection = self._connection()
        channel = connection.channel()
        channel.exchange_declare(exchange=self.COMMAND_EXCHANGE, exchange_type="direct", durable=True)
        channel.exchange_declare(exchange=self.DEAD_LETTER_EXCHANGE, exchange_type="direct", durable=True)
        channel.queue_declare(
            queue=self.COMMAND_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": 120000,
                "x-dead-letter-exchange": self.DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": "vm.commands.dlq",
            },
        )
        channel.queue_bind(queue=self.COMMAND_QUEUE, exchange=self.COMMAND_EXCHANGE, routing_key="image.sync")
        channel.queue_declare(queue=self.DEAD_LETTER_QUEUE, durable=True)
        channel.queue_bind(
            queue=self.DEAD_LETTER_QUEUE,
            exchange=self.DEAD_LETTER_EXCHANGE,
            routing_key="vm.commands.dlq",
        )
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
