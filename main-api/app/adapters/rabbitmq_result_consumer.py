from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from uuid import UUID

import pika
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.postgres import PostgresInstanceRepository, PostgresTaskRepository
from app.application.services.task_result_processor import (
    NonRetryableResultEventError,
    RetryableResultEventError,
    TaskResultProcessor,
    VmResultEvent,
)

logger = logging.getLogger(__name__)


class RabbitMqVmResultConsumer:
    RESULT_EXCHANGE = "vm.results"
    RESULT_QUEUE = "main-api.vm-results.q"
    RESULT_ROUTING_KEY = "instance.result"
    RESULT_DLX = "vm.results.dlx"
    RESULT_DLQ = "main-api.vm-results.dlq"
    RESULT_DLQ_ROUTING_KEY = "main-api.vm-results.dlq"

    def __init__(self, amqp_url: str, session_factory: sessionmaker[Session]):
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
        self._thread = threading.Thread(target=self._run, name="vm-result-consumer", daemon=True)
        self._thread.start()

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        return self._ready_event.wait(timeout=timeout)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._ready_event.clear()

    def _connection(self):
        parameters = pika.URLParameters(self.amqp_url)
        parameters.heartbeat = 30
        parameters.blocked_connection_timeout = 30
        return pika.BlockingConnection(parameters)

    def _declare(self, channel) -> None:
        channel.exchange_declare(exchange=self.RESULT_EXCHANGE, exchange_type="direct", durable=True)
        channel.exchange_declare(exchange=self.RESULT_DLX, exchange_type="direct", durable=True)
        channel.queue_declare(
            queue=self.RESULT_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.RESULT_DLX,
                "x-dead-letter-routing-key": self.RESULT_DLQ_ROUTING_KEY,
            },
        )
        channel.queue_bind(
            queue=self.RESULT_QUEUE,
            exchange=self.RESULT_EXCHANGE,
            routing_key=self.RESULT_ROUTING_KEY,
        )
        channel.queue_declare(queue=self.RESULT_DLQ, durable=True)
        channel.queue_bind(
            queue=self.RESULT_DLQ,
            exchange=self.RESULT_DLX,
            routing_key=self.RESULT_DLQ_ROUTING_KEY,
        )

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

    def _run(self) -> None:
        while not self._stop_event.is_set():
            connection = None
            channel = None
            try:
                connection = self._connection()
                channel = connection.channel()
                self._declare(channel)
                self._ready_event.set()

                for method, _, body in channel.consume(self.RESULT_QUEUE, inactivity_timeout=1, auto_ack=False):
                    if self._stop_event.is_set():
                        break
                    if method is None:
                        continue

                    try:
                        payload = json.loads(body.decode("utf-8"))
                        event = self._parse_event(payload)
                        with self.session_factory() as session:
                            processor = TaskResultProcessor(
                                instance_repo=PostgresInstanceRepository(session),
                                task_repo=PostgresTaskRepository(session),
                            )
                            processor.process(event)
                            session.commit()
                        channel.basic_ack(method.delivery_tag)
                    except RetryableResultEventError:
                        channel.basic_nack(method.delivery_tag, requeue=True)
                        time.sleep(0.5)
                    except OperationalError:
                        logger.exception("temporary database error while processing vm result event")
                        channel.basic_nack(method.delivery_tag, requeue=True)
                        time.sleep(0.5)
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError, NonRetryableResultEventError):
                        logger.exception("non-retryable vm result event")
                        channel.basic_nack(method.delivery_tag, requeue=False)
                    except Exception:
                        logger.exception("unexpected vm result processing failure; routing to DLQ")
                        channel.basic_nack(method.delivery_tag, requeue=False)
            except Exception:
                logger.exception("vm result consumer loop failed")
                time.sleep(2)
            finally:
                try:
                    if channel and channel.is_open:
                        channel.close()
                except Exception:
                    pass
                try:
                    if connection and connection.is_open:
                        connection.close()
                except Exception:
                    pass
