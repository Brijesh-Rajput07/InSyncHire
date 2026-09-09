# LOCATION: shared/insynchire-events/insynchire_events/exceptions.py

"""Typed exceptions for insynchire_events.

Services should catch these specifically rather than bare Exception, so
that Kafka-layer failures are never confused with business logic errors.
"""

from __future__ import annotations


class InsyncHireEventsError(Exception):
    """Base class for all errors raised by this package."""


class EventValidationError(InsyncHireEventsError):
    """Raised when an inbound or outbound payload fails schema validation.

    Carries the raw payload so it can be routed to a DLQ without being lost.
    """

    def __init__(self, message: str, raw_payload: bytes | str | None = None):
        super().__init__(message)
        self.raw_payload = raw_payload


class EventPublishError(InsyncHireEventsError):
    """Raised when an event could not be published after exhausting retries.

    The internal producer has already routed the event to the topic's DLQ
    by the time this is raised — callers should log/alert, not re-attempt
    the same publish.
    """

    def __init__(self, message: str, topic: str, attempts: int):
        super().__init__(message)
        self.topic = topic
        self.attempts = attempts


class UnknownTopicError(InsyncHireEventsError):
    """Raised when publish()/subscribe() is called with a topic that has
    no registered schema in EVENT_SCHEMA_REGISTRY."""
