from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
from datetime import datetime, timezone
from uuid import UUID

import aio_pika
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.postgres_repositories import (
    PostgresInstanceRepository,
    PostgresTaskRepository,
)
from app.application.services.task_result_processor import (
    NonRetryableResultEventError,
    RetryableResultEventError,
    TaskResultProcessor,
    VmResultEvent,
)

logger = logging.getLogger(__name__)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class RabbitMqVmResultConsumer:
    RESULT_EXCHANGE = "vm.results"
    RESULT_QUEUE = "main-api.vm-results.q"
    RESULT_ROUTING_KEY = "instance.result"
    RESULT_DLX = "vm.results.dlx"
    RESULT_DLQ = "main-api.vm-results.dlq"
    RESULT_DLQ_ROUTING_KEY = "main-api.vm-results.dlq"

    def __init__(
        self, amqp_url: str, session_factory: async_sessionmaker[AsyncSession]
    ):
        self.amqp_url = amqp_url
        self.session_factory = session_factory
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._thread = threading.Thread(
            target=self._run_thread, name="vm-result-consumer", daemon=True
        )
        self._thread.start()

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        return self._ready_event.wait(timeout=timeout)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._ready_event.clear()

    def _run_thread(self) -> None:
        asyncio.run(self._run())

    async def _connection(self):
        return await aio_pika.connect_robust(self.amqp_url)

    async def _declare(self, channel):
        result_exchange = await channel.declare_exchange(
            self.RESULT_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        result_dlx = await channel.declare_exchange(
            self.RESULT_DLX, aio_pika.ExchangeType.DIRECT, durable=True
        )
        queue = await channel.declare_queue(
            self.RESULT_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.RESULT_DLX,
                "x-dead-letter-routing-key": self.RESULT_DLQ_ROUTING_KEY,
            },
        )
        await queue.bind(result_exchange, routing_key=self.RESULT_ROUTING_KEY)

        dlq = await channel.declare_queue(self.RESULT_DLQ, durable=True)
        await dlq.bind(result_dlx, routing_key=self.RESULT_DLQ_ROUTING_KEY)
        return queue

    def _parse_event(self, payload: dict) -> VmResultEvent:
        ts = payload.get("timestamp")
        if ts:
            event_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            event_time = datetime.now(timezone.utc)
        return VmResultEvent(
            task_id=UUID(payload["task_id"]),
            request_id=UUID(payload["request_id"]),
            instance_id=UUID(payload["instance_id"]),
            command=payload["command"],
            status=payload["status"],
            attempt_count=int(payload.get("attempt_count", 0)),
            result=payload.get("result"),
            error_code=payload.get("error_code"),
            error_message=payload.get("error_message"),
            timestamp=event_time,
        )

    async def _process_event(self, event: VmResultEvent):
        session_ctx = self.session_factory()
        if hasattr(session_ctx, "__aenter__"):
            async with session_ctx as session:
                processor = TaskResultProcessor(
                    instance_repo=PostgresInstanceRepository(session),
                    task_repo=PostgresTaskRepository(session),
                )
                await _maybe_await(processor.process(event))
                await _maybe_await(session.commit())
            return

        with session_ctx as session:
            processor = TaskResultProcessor(
                instance_repo=PostgresInstanceRepository(session),
                task_repo=PostgresTaskRepository(session),
            )
            await _maybe_await(processor.process(event))
            await _maybe_await(session.commit())

    async def _run_async(self) -> None:
        while not self._stop_event.is_set():
            connection = None
            channel = None
            try:
                connection = await _maybe_await(self._connection())
                channel = await _maybe_await(connection.channel())

                declared = self._declare(channel)
                queue = await _maybe_await(declared)
                self._ready_event.set()

                if hasattr(channel, "consume"):
                    for method, _, body in channel.consume(
                        self.RESULT_QUEUE, inactivity_timeout=1, auto_ack=False
                    ):
                        if self._stop_event.is_set():
                            break
                        if method is None:
                            continue

                        try:
                            payload = json.loads(body.decode("utf-8"))
                            event = self._parse_event(payload)
                            await self._process_event(event)
                            channel.basic_ack(method.delivery_tag)
                        except RetryableResultEventError:
                            channel.basic_nack(method.delivery_tag, requeue=True)
                            await asyncio.sleep(0.5)
                        except OperationalError:
                            logger.exception(
                                "temporary database error while processing vm result event"
                            )
                            channel.basic_nack(method.delivery_tag, requeue=True)
                            await asyncio.sleep(0.5)
                        except (
                            json.JSONDecodeError,
                            KeyError,
                            TypeError,
                            ValueError,
                            NonRetryableResultEventError,
                        ):
                            logger.exception("non-retryable vm result event")
                            channel.basic_nack(method.delivery_tag, requeue=False)
                        except Exception:
                            logger.exception(
                                "unexpected vm result processing failure; routing to DLQ"
                            )
                            channel.basic_nack(method.delivery_tag, requeue=False)
                    continue

                async with queue.iterator() as iterator:
                    async for message in iterator:
                        if self._stop_event.is_set():
                            break
                        try:
                            payload = json.loads(message.body.decode("utf-8"))
                            event = self._parse_event(payload)
                            await self._process_event(event)
                            await message.ack()
                        except RetryableResultEventError:
                            await message.reject(requeue=True)
                            await asyncio.sleep(0.5)
                        except OperationalError:
                            logger.exception(
                                "temporary database error while processing vm result event"
                            )
                            await message.reject(requeue=True)
                            await asyncio.sleep(0.5)
                        except (
                            json.JSONDecodeError,
                            KeyError,
                            TypeError,
                            ValueError,
                            NonRetryableResultEventError,
                        ):
                            logger.exception("non-retryable vm result event")
                            await message.reject(requeue=False)
                        except Exception:
                            logger.exception(
                                "unexpected vm result processing failure; routing to DLQ"
                            )
                            await message.reject(requeue=False)
            except Exception:
                logger.exception("vm result consumer loop failed")
                await asyncio.sleep(2)
            finally:
                try:
                    if channel and getattr(channel, "is_open", True):
                        await _maybe_await(channel.close())
                except Exception:
                    pass
                try:
                    if connection and getattr(connection, "is_open", True):
                        await _maybe_await(connection.close())
                except Exception:
                    pass

    async def _run(self) -> None:
        await self._run_async()
