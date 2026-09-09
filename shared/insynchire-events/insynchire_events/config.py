# LOCATION: shared/insynchire-events/insynchire_events/config.py

"""
Kafka configuration, loaded from environment variables.

No secrets or broker addresses are ever hardcoded — this matches
Section 10i of the project plan (secrets via env / secrets manager only).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        )
    )
    security_protocol: str = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    sasl_mechanism: str | None = os.getenv("KAFKA_SASL_MECHANISM") or None
    sasl_plain_username: str | None = os.getenv("KAFKA_SASL_USERNAME") or None
    sasl_plain_password: str | None = os.getenv("KAFKA_SASL_PASSWORD") or None

    # Producer tuning
    max_publish_retries: int = int(os.getenv("KAFKA_MAX_PUBLISH_RETRIES", "3"))
    retry_backoff_base_seconds: float = float(
        os.getenv("KAFKA_RETRY_BACKOFF_BASE_SECONDS", "0.5")
    )
    acks: str = os.getenv("KAFKA_PRODUCER_ACKS", "all")

    # Consumer tuning
    consumer_group_prefix: str = os.getenv("KAFKA_CONSUMER_GROUP_PREFIX", "insynchire")
    auto_offset_reset: str = os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest")
    enable_auto_commit: bool = os.getenv("KAFKA_ENABLE_AUTO_COMMIT", "false").lower() == "true"

    def aiokafka_common_kwargs(self) -> dict:
        """Kwargs shared by AIOKafkaProducer and AIOKafkaConsumer."""
        kwargs: dict = {
            "bootstrap_servers": ",".join(self.bootstrap_servers),
            "security_protocol": self.security_protocol,
        }
        if self.sasl_mechanism:
            kwargs["sasl_mechanism"] = self.sasl_mechanism
            kwargs["sasl_plain_username"] = self.sasl_plain_username
            kwargs["sasl_plain_password"] = self.sasl_plain_password
        return kwargs


_cached_config: KafkaConfig | None = None


def get_kafka_config() -> KafkaConfig:
    """Return a process-wide cached KafkaConfig instance."""
    global _cached_config
    if _cached_config is None:
        _cached_config = KafkaConfig()
    return _cached_config
