# LOCATION: shared/insynchire-events/insynchire_events/consumer.py

"""
Subscribe helper: every service calls `subscribe(topic, handler, group_id)`
instead of touching aiokafka directly. Handles deserialization, schema
validation, and routing bad/failed messages to the topic's DLQ instead of
crashing the consumer loop or silently dropping them.
"""

from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from .config import KafkaConfig, get_kafka_config
from .exceptions import UnknownTopicError
from .schemas import BaseEvent, schema_for_topic

logger = logging.getLogger("insynchire_events.consumer")

Handler = Callable[[BaseEvent], Awaitable[None]]


class EventConsumer:
    """Consumes one topic, validates each message against its registered
    schema, and dispatches to `handler`. Messages that fail validation or
    whose handler raises are routed to the topic's `.dlq` topic rather
    than being retried forever or dropped silently.
    """

    def __init__(
        self,
        topic: str,
        handler: Handler,
        group_id: str,
        config: KafkaConfig | None = None,
    ):
        self._topic = topic
        self._handler = handler
        self._group_id = group_id
        self._config = config or get_kafka_config()
        self._consumer: AIOKafkaConsumer | None = None
        self._dlq_producer: AIOKafkaProducer | None = None

        try:
            self._schema = schema_for_topic(topic)
        except KeyError as exc:
            raise UnknownTopicError(f"No schema registered for topic '{topic}'") from exc

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self._topic,
            **self._config.aiokafka_common_kwargs(),
            group_id=self._group_id,
            auto_offset_reset=self._config.auto_offset_reset,
            enable_auto_commit=self._config.enable_auto_commit,
        )
        await self._consumer.start()

        self._dlq_producer = AIOKafkaProducer(**self._config.aiokafka_common_kwargs())
        await self._dlq_producer.start()

        logger.info("EventConsumer started topic=%s group=%s", self._topic, self._group_id)

    async def stop(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
        if self._dlq_producer is not None:
            await self._dlq_producer.stop()

    async def run_forever(self) -> None:
        """Main consume loop. Call inside `asyncio.run()` from the
        service's headless entrypoint (e.g. migration_service/main.py)."""
        if self._consumer is None:
            await self.start()

        assert self._consumer is not None
        async for msg in self._consumer:
            await self._handle_message(msg)
            if not self._config.enable_auto_commit:
                await self._consumer.commit()

    async def _handle_message(self, msg) -> None:
        raw_value = msg.value
        try:
            data = json.loads(raw_value.decode("utf-8"))
            event = self._schema.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "schema validation failed on topic=%s offset=%s: %s",
                self._topic, msg.offset, exc,
            )
            await self._route_to_dlq(raw_value, reason=f"validation_error: {exc}")
            return

        try:
            await self._handler(event)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "handler raised for event_id=%s topic=%s: %s",
                event.event_id, self._topic, exc,
            )
            await self._route_to_dlq(raw_value, reason=f"handler_error: {exc}")

    async def _route_to_dlq(self, raw_value: bytes, reason: str) -> None:
        if self._dlq_producer is None:
            logger.critical("DLQ producer not started — dropping message on topic=%s", self._topic)
            return
        dlq_topic = f"{self._topic}.dlq"
        try:
            wrapped = json.dumps(
                {
                    "original_topic": self._topic,
                    "reason": reason,
                    "payload": raw_value.decode("utf-8", errors="replace"),
                }
            ).encode("utf-8")
            await self._dlq_producer.send_and_wait(dlq_topic, value=wrapped)
        except Exception as dlq_exc:  # noqa: BLE001
            logger.critical("FAILED TO WRITE TO DLQ %s: %s", dlq_topic, dlq_exc)


async def subscribe(
    topic: str,
    handler: Handler,
    group_id: str,
    config: KafkaConfig | None = None,
) -> None:
    """Convenience wrapper: creates an EventConsumer and runs it forever.

    Example (inside a headless service's main.py):

        async def handle_signup(event: TenantSignupInitiatedEvent) -> None:
            await provision_tenant_db(event.tenant_id)

        await subscribe(
            Topics.TENANT_SIGNUP_INITIATED.value,
            handle_signup,
            group_id="migration_service",
        )
    """
    consumer = EventConsumer(topic, handler, group_id, config)
    await consumer.start()
    try:
        await consumer.run_forever()
    finally:
        await consumer.stop()
