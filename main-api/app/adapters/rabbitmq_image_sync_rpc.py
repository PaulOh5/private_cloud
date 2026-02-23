from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import aio_pika

from app.infra.rabbitmq import (
    COMMAND_EXCHANGE,
    open_connection,
    setup_vm_command_topology,
)
from app.ports import VmImageSyncError, VmImageSyncPort


class VmImageSyncRpcError(VmImageSyncError):
    pass


class RabbitMqVmImageSyncRpcAdapter(VmImageSyncPort):
    _ROUTING_KEYS = ("image.sync",)

    def __init__(self, amqp_url: str, timeout_seconds: int):
        self.amqp_url = amqp_url
        self.timeout_seconds = max(int(timeout_seconds), 1)

    async def sync_images(self) -> dict:
        connection = await open_connection(self.amqp_url)
        try:
            channel = await connection.channel()
            await setup_vm_command_topology(channel, routing_keys=self._ROUTING_KEYS)
            exchange = await channel.get_exchange(COMMAND_EXCHANGE)

            callback_queue = await channel.declare_queue(
                exclusive=True, auto_delete=True
            )
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
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode("utf-8"),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    correlation_id=correlation_id,
                    reply_to=callback_queue.name,
                ),
                routing_key="image.sync",
            )

            deadline = time.monotonic() + self.timeout_seconds
            async with callback_queue.iterator() as iterator:
                async for incoming in iterator:
                    async with incoming.process(ignore_processed=True):
                        if incoming.correlation_id != correlation_id:
                            continue
                        payload = json.loads(incoming.body.decode("utf-8"))
                        if bool(payload.get("success")):
                            result = payload.get("result")
                            return result if isinstance(result, dict) else {}
                        raise VmImageSyncRpcError(
                            code=str(payload.get("error_code") or "QEMU_ERROR"),
                            message=str(
                                payload.get("error_message") or "image sync failed"
                            ),
                        )
                    if time.monotonic() >= deadline:
                        break

            raise VmImageSyncRpcError("TIMEOUT", "image sync command timed out")
        finally:
            await connection.close()
