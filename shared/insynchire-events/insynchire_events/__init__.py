# LOCATION: shared/insynchire-events/insynchire_events/__init__.py

"""
insynchire_events
==================

Internal shared contract package for InSyncHire.

Every microservice imports this package instead of writing raw Kafka
producer/consumer code. It owns:

  - Pydantic v2 schemas for every event that crosses the Kafka bus
  - `publish()` — serialize + send + retry + dead-letter routing
  - `subscribe()` — consume + validate + dispatch to a handler + DLQ on failure
  - The canonical list of topic names (see `topics.py`)

Changing a schema here is a breaking change for every service that reads
that topic. Bump `schema_version` on the affected event and coordinate
the rollout — do not silently change field types or remove fields.
"""

from .config import KafkaConfig, get_kafka_config
from .exceptions import (
    EventPublishError,
    EventValidationError,
    InsyncHireEventsError,
    UnknownTopicError,
)
from .producer import EventProducer, publish
from .consumer import EventConsumer, subscribe
from .topics import Topics
from . import schemas

__all__ = [
    "KafkaConfig",
    "get_kafka_config",
    "InsyncHireEventsError",
    "EventPublishError",
    "EventValidationError",
    "UnknownTopicError",
    "EventProducer",
    "publish",
    "EventConsumer",
    "subscribe",
    "Topics",
    "schemas",
]

__version__ = "0.1.0"
