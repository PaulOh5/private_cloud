from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import pika

from app.ports.interfaces import VmProvisioningPort


class RabbitMqVmProvisioningAdapter(VmProvisioningPort):
    COMMAND_EXCHANGE = "vm.commands"
    COMMAND_QUEUE = "vm.commands.q"
    DEAD_LETTER_EXCHANGE = "vm.commands.dlx"
    DEAD_LETTER_QUEUE = "vm.commands.dlq"

    RESULT_EXCHANGE = "vm.results"
    RESULT_QUEUE = "main-api.vm-results.q"
    RESULT_ROUTING_KEY = "instance.result"

    def __init__(self, amqp_url: str):
        self.amqp_url = amqp_url
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
        channel.exchange_declare(exchange=self.RESULT_EXCHANGE, exchange_type="direct", durable=True)

        channel.queue_declare(
            queue=self.COMMAND_QUEUE,
            durable=True,
            arguments={
                "x-message-ttl": 120000,
                "x-dead-letter-exchange": self.DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": "vm.commands.dlq",
            },
        )
        channel.queue_bind(queue=self.COMMAND_QUEUE, exchange=self.COMMAND_EXCHANGE, routing_key="instance.create")
        channel.queue_bind(queue=self.COMMAND_QUEUE, exchange=self.COMMAND_EXCHANGE, routing_key="instance.update")
        channel.queue_bind(queue=self.COMMAND_QUEUE, exchange=self.COMMAND_EXCHANGE, routing_key="instance.delete")
        channel.queue_bind(queue=self.COMMAND_QUEUE, exchange=self.COMMAND_EXCHANGE, routing_key="instance.cancel")

        channel.queue_declare(queue=self.DEAD_LETTER_QUEUE, durable=True)
        channel.queue_bind(
            queue=self.DEAD_LETTER_QUEUE,
            exchange=self.DEAD_LETTER_EXCHANGE,
            routing_key="vm.commands.dlq",
        )

        channel.queue_declare(queue=self.RESULT_QUEUE, durable=True)
        channel.queue_bind(
            queue=self.RESULT_QUEUE,
            exchange=self.RESULT_EXCHANGE,
            routing_key=self.RESULT_ROUTING_KEY,
        )

        channel.close()
        connection.close()

    def publish_command(self, command: str, payload: dict, task_id: UUID, request_id: UUID) -> None:
        connection = self._connection()
        channel = connection.channel()

        message = {
            "task_id": str(task_id),
            "request_id": str(request_id),
            "instance_id": payload.get("instance_id"),
            "command": command,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "correlation_id": str(task_id),
        }

        channel.basic_publish(
            exchange=self.COMMAND_EXCHANGE,
            routing_key=command,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                correlation_id=str(task_id),
            ),
            body=json.dumps(message).encode("utf-8"),
        )
        channel.close()
        connection.close()
