from __future__ import annotations

from collections.abc import Iterable

import aio_pika

COMMAND_EXCHANGE = "vm.commands"
COMMAND_QUEUE = "vm.commands.q"
DEAD_LETTER_EXCHANGE = "vm.commands.dlx"
DEAD_LETTER_QUEUE = "vm.commands.dlq"
DEAD_LETTER_ROUTING_KEY = "vm.commands.dlq"
COMMAND_QUEUE_TTL_MS = 120000


async def open_connection(amqp_url: str) -> aio_pika.abc.AbstractRobustConnection:
    return await aio_pika.connect_robust(amqp_url)


async def setup_vm_command_topology(
    channel: aio_pika.abc.AbstractChannel, *, routing_keys: Iterable[str]
) -> None:
    command_exchange = await channel.declare_exchange(
        COMMAND_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )
    dead_letter_exchange = await channel.declare_exchange(
        DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )

    command_queue = await channel.declare_queue(
        COMMAND_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": COMMAND_QUEUE_TTL_MS,
            "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
            "x-dead-letter-routing-key": DEAD_LETTER_ROUTING_KEY,
        },
    )
    for routing_key in dict.fromkeys(routing_keys):
        await command_queue.bind(command_exchange, routing_key=routing_key)

    dead_letter_queue = await channel.declare_queue(DEAD_LETTER_QUEUE, durable=True)
    await dead_letter_queue.bind(
        dead_letter_exchange, routing_key=DEAD_LETTER_ROUTING_KEY
    )
