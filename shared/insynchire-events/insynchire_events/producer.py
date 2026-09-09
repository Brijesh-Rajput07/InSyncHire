# LOCATION: shared/insynchire-events/insynchire_events/producer.py

"""
Publish helper: every service calls `publish(topic, event)` instead of
touching aiokafka directly. Handles serialization, bounded retries with
backoff, and routing to the topic's dead-letter queue if all retries fail.
"""

from __future__ import annotations

import asyncio
import json
import logging

from aiokafka import AIOKafkaProducer

from .config import KafkaConfig, get_kafka_config
from .exceptions import EventPublishError, EventValidationError, UnknownTopicError
from .schemas import BaseEvent, schema_for_topic
from .topics import Topics

logger = logging.getLogger("insynchire_events.producer")


class EventProducer:
    """Wraps a single AIOKafkaProducer instance with retry + DLQ logic.

    Intended to be instantiated once per service process (e.g. at FastAPI
    startup) and reused, rather than created per-request — Kafka producer
    connection setup is not free.
    """

    def __init__(self, config: KafkaConfig | None = None):
        self._config = config or get_kafka_config()
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        if self._producer is not None:
            return
        self._producer = AIOKafkaProducer(
            **self._config.aiokafka_common_kwargs(),
            acks=self._config.acks,
            enable_idempotence=True,
        )
        await self._producer.start()
        logger.info("EventProducer started against %s", self._config.bootstrap_servers)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, topic: str, event: BaseEvent) -> None:
        """Serialize, validate, and publish `event` to `topic`.

        On repeated transport failure, the event is sent to the topic's
        `.dlq` topic instead of being dropped, and `EventPublishError` is
        still raised so the caller's own error-handling/logging fires.
        """
        if self._producer is None:
            await self.start()

        expected_schema = _safe_schema_for_topic(topic)
        if not isinstance(event, expected_schema):
            raise EventValidationError(
                f"Event of type {type(event).__name__} does not match "
                f"registered schema {expected_schema.__name__} for topic '{topic}'"
            )

        payload_bytes = event.model_dump_json().encode("utf-8")
        key_bytes = str(event.tenant_id or event.event_id).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(1, self._config.max_publish_retries + 1):
            try:
                await self._producer.send_and_wait(topic, value=payload_bytes, key=key_bytes)
                logger.info(
                    "published event=%s topic=%s trace_id=%s attempt=%d",
                    event.event_id, topic, event.trace_id, attempt,
                )
                return
            except Exception as exc:  # noqa: BLE001 - broad on purpose: retry any transport error
                last_error = exc
                backoff = self._config.retry_backoff_base_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "publish attempt %d/%d failed for topic=%s: %s (retrying in %.2fs)",
                    attempt, self._config.max_publish_retries, topic, exc, backoff,
                )
                await asyncio.sleep(backoff)

        # Exhausted retries — route to DLQ so the event isn't lost.
        await self._send_to_dlq(topic, payload_bytes, key_bytes, last_error)
        raise EventPublishError(
            f"Failed to publish to '{topic}' after {self._config.max_publish_retries} attempts: {last_error}",
            topic=topic,
            attempts=self._config.max_publish_retries,
        )

    async def _send_to_dlq(
        self, original_topic: str, payload_bytes: bytes, key_bytes: bytes, error: Exception | None
    ) -> None:
        dlq_topic = f"{original_topic}.dlq"
        try:
            wrapped = json.dumps(
                {
                    "original_topic": original_topic,
                    "error": str(error),
                    "payload": payload_bytes.decode("utf-8"),
                }
            ).encode("utf-8")
            await self._producer.send_and_wait(dlq_topic, value=wrapped, key=key_bytes)
            logger.error("routed failed event to DLQ topic=%s", dlq_topic)
        except Exception as dlq_exc:  # noqa: BLE001
            # If even the DLQ send fails, this is a critical infra problem —
            # log loudly. There is nowhere further to route it.
            logger.critical(
                "FAILED TO WRITE TO DLQ %s — event may be lost: %s", dlq_topic, dlq_exc
            )


def _safe_schema_for_topic(topic: str):
    try:
        return schema_for_topic(topic)
    except KeyError as exc:
        raise UnknownTopicError(
            f"No schema registered for topic '{topic}'. "
            f"Valid topics: {Topics.all_topics()}"
        ) from exc


# ─────────────────────────────────────────────────────────────────────────
# Module-level convenience singleton + function, so simple call sites can
# do `from insynchire_events import publish` without managing a producer
# instance themselves. Services with stricter lifecycle needs (FastAPI
# app with startup/shutdown hooks) should use EventProducer directly and
# wire start()/stop() into the app lifespan.
# ─────────────────────────────────────────────────────────────────────────

_default_producer: EventProducer | None = None


async def publish(topic: str, event: BaseEvent) -> None:
    global _default_producer
    if _default_producer is None:
        _default_producer = EventProducer()
        await _default_producer.start()
    await _default_producer.publish(topic, event)
