from __future__ import annotations

from collections.abc import Iterable

import pika

COMMAND_EXCHANGE = "vm.commands"
COMMAND_QUEUE = "vm.commands.q"
DEAD_LETTER_EXCHANGE = "vm.commands.dlx"
DEAD_LETTER_QUEUE = "vm.commands.dlq"
DEAD_LETTER_ROUTING_KEY = "vm.commands.dlq"
COMMAND_QUEUE_TTL_MS = 120000


def open_blocking_connection(amqp_url: str) -> pika.BlockingConnection:
    parameters = pika.URLParameters(amqp_url)
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 30
    return pika.BlockingConnection(parameters)


def setup_vm_command_topology(channel, *, routing_keys: Iterable[str]) -> None:
    channel.exchange_declare(exchange=COMMAND_EXCHANGE, exchange_type="direct", durable=True)
    channel.exchange_declare(exchange=DEAD_LETTER_EXCHANGE, exchange_type="direct", durable=True)

    channel.queue_declare(
        queue=COMMAND_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": COMMAND_QUEUE_TTL_MS,
            "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
            "x-dead-letter-routing-key": DEAD_LETTER_ROUTING_KEY,
        },
    )
    for routing_key in dict.fromkeys(routing_keys):
        channel.queue_bind(queue=COMMAND_QUEUE, exchange=COMMAND_EXCHANGE, routing_key=routing_key)

    channel.queue_declare(queue=DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(
        queue=DEAD_LETTER_QUEUE,
        exchange=DEAD_LETTER_EXCHANGE,
        routing_key=DEAD_LETTER_ROUTING_KEY,
    )
