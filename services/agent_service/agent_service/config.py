# LOCATION: services/agent_service/agent_service/config.py

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentServiceConfig:
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_consumer_group: str = os.getenv("AGENT_SERVICE_KAFKA_GROUP", "agent_service")

    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )
    connection_string_encryption_key: str | None = os.getenv("CONNECTION_STRING_ENCRYPTION_KEY")

    input_length_limits: dict[str, int] = field(
        default_factory=lambda: {
            "code_analysis": int(os.getenv("GUARDRAIL_INPUT_LIMIT_CODE_ANALYSIS", "50000")),
            "question_strategist": int(os.getenv("GUARDRAIL_INPUT_LIMIT_QUESTION_STRATEGIST", "10000")),
            "report_synthesis": int(os.getenv("GUARDRAIL_INPUT_LIMIT_REPORT_SYNTHESIS", "200000")),
        }
    )

    circuit_breaker_max_triggers: int = int(os.getenv("GUARDRAIL_CIRCUIT_BREAKER_MAX_TRIGGERS", "5"))
    circuit_breaker_window_seconds: float = float(os.getenv("GUARDRAIL_CIRCUIT_BREAKER_WINDOW_SECONDS", "60"))
    circuit_breaker_cooldown_seconds: float = float(os.getenv("GUARDRAIL_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "300"))

    integrity_escalation_max_signals: int = int(os.getenv("GUARDRAIL_INTEGRITY_ESCALATION_MAX_SIGNALS", "5"))
    integrity_escalation_window_seconds: float = float(
        os.getenv("GUARDRAIL_INTEGRITY_ESCALATION_WINDOW_SECONDS", "1800")
    )

    output_schema_max_retries: int = int(os.getenv("GUARDRAIL_OUTPUT_SCHEMA_MAX_RETRIES", "2"))

    guardrail_debug_log_enabled: bool = os.getenv("GUARDRAIL_DEBUG_LOG_ENABLED", "false").lower() == "true"

    # M10: human-in-the-loop timeout policy knobs (Rule 5.3), reused by
    # interview_graph.py's interrupt nodes.
    question_suggestion_timeout_seconds: float = float(os.getenv("QUESTION_SUGGESTION_TIMEOUT_SECONDS", "60"))
    phase_transition_alert_seconds: float = float(os.getenv("PHASE_TRANSITION_ALERT_SECONDS", "300"))


_cached: AgentServiceConfig | None = None


def get_config() -> AgentServiceConfig:
    global _cached
    if _cached is None:
        _cached = AgentServiceConfig()
    return _cached