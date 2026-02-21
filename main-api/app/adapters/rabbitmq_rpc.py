from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import pika

from app.infra.messaging.rabbitmq import (
    COMMAND_EXCHANGE,
    COMMAND_QUEUE,
    DEAD_LETTER_EXCHANGE,
    DEAD_LETTER_QUEUE,
    open_blocking_connection,
    setup_vm_command_topology,
)
from app.ports import VmProvisioningPort


class RabbitMqVmProvisioningAdapter(VmProvisioningPort):
    COMMAND_EXCHANGE = COMMAND_EXCHANGE
    COMMAND_QUEUE = COMMAND_QUEUE
    DEAD_LETTER_EXCHANGE = DEAD_LETTER_EXCHANGE
    DEAD_LETTER_QUEUE = DEAD_LETTER_QUEUE
    _ROUTING_KEYS = (
        "instance.create",
        "instance.update",
        "instance.delete",
        "instance.start",
        "instance.stop",
        "instance.cancel",
        "image.sync",
    )

    def __init__(self, amqp_url: str):
        self.amqp_url = amqp_url
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

    def publish_command(self, command: str, payload: dict, task_id: UUID, request_id: UUID) -> None:
        connection = self._connection()
        channel = connection.channel()
        channel.confirm_delivery()

        message = {
            "task_id": str(task_id),
            "request_id": str(request_id),
            "instance_id": payload.get("instance_id"),
            "command": command,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "correlation_id": str(task_id),
        }

        published = channel.basic_publish(
            exchange=self.COMMAND_EXCHANGE,
            routing_key=command,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                correlation_id=str(task_id),
                message_id=str(task_id),
            ),
            body=json.dumps(message).encode("utf-8"),
        )
        if published is False:  # pragma: no cover
            raise RuntimeError("rabbitmq publish was not confirmed")
        channel.close()
        connection.close()
