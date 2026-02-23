from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import aio_pika

from app.infra.rabbitmq import (
    COMMAND_EXCHANGE,
    open_connection,
    setup_vm_command_topology,
)
from app.ports import VmProvisioningPort


class RabbitMqVmProvisioningAdapter(VmProvisioningPort):
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

    async def publish_command(
        self, command: str, payload: dict, task_id: UUID, request_id: UUID
    ) -> None:
        connection = await open_connection(self.amqp_url)
        try:
            channel = await connection.channel(publisher_confirms=True)
            await setup_vm_command_topology(channel, routing_keys=self._ROUTING_KEYS)
            exchange = await channel.get_exchange(COMMAND_EXCHANGE)

            message = {
                "task_id": str(task_id),
                "request_id": str(request_id),
                "instance_id": payload.get("instance_id"),
                "command": command,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
                "correlation_id": str(task_id),
            }
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode("utf-8"),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    correlation_id=str(task_id),
                    message_id=str(task_id),
                ),
                routing_key=command,
            )
        finally:
            await connection.close()
