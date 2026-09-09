# LOCATION: services/agent_service/agent_service/config.py

"""
Env-based configuration for the Agent Service (M6). All secrets/tunables
come from environment variables only (Section 10i) -- nothing here is
hardcoded.

The guardrail policy knobs here (length limits, circuit breaker window,
escalation thresholds, output-retry count) are the exact numbers named
in the project plan's GUARDRAILS ARCHITECTURE section, made configurable
rather than literal constants buried in guardrail code -- so a future
tuning pass (e.g. "Report Synthesis needs a higher length limit") is an
env change, not a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentServiceConfig:
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_consumer_group: str = os.getenv("AGENT_SERVICE_KAFKA_GROUP", "agent_service")

    # Only needed once persistence to agent_decision_logs/agent_guardrail_logs
    # is wired up (M10) -- not required for M6's standalone GuardrailService.
    global_db_dsn: str = os.getenv(
        "GLOBAL_DB_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5433/insynchire_global"
    )
    connection_string_encryption_key: str | None = os.getenv("CONNECTION_STRING_ENCRYPTION_KEY")

    # Layer 1 Rule 1.2 -- input length limits (per agent context)
    input_length_limits: dict[str, int] = field(
        default_factory=lambda: {
            "code_analysis": int(os.getenv("GUARDRAIL_INPUT_LIMIT_CODE_ANALYSIS", "50000")),
            "question_strategist": int(os.getenv("GUARDRAIL_INPUT_LIMIT_QUESTION_STRATEGIST", "10000")),
            "report_synthesis": int(os.getenv("GUARDRAIL_INPUT_LIMIT_REPORT_SYNTHESIS", "200000")),
        }
    )

    # Layer 5 Rule 5.2 -- circuit breaker
    circuit_breaker_max_triggers: int = int(os.getenv("GUARDRAIL_CIRCUIT_BREAKER_MAX_TRIGGERS", "5"))
    circuit_breaker_window_seconds: float = float(os.getenv("GUARDRAIL_CIRCUIT_BREAKER_WINDOW_SECONDS", "60"))
    circuit_breaker_cooldown_seconds: float = float(os.getenv("GUARDRAIL_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "300"))

    # Layer 5 Rule 5.4 -- integrity flag escalation
    integrity_escalation_max_signals: int = int(os.getenv("GUARDRAIL_INTEGRITY_ESCALATION_MAX_SIGNALS", "5"))
    integrity_escalation_window_seconds: float = float(
        os.getenv("GUARDRAIL_INTEGRITY_ESCALATION_WINDOW_SECONDS", "1800")
    )

    # Layer 2 Rule 2.1 -- output schema validation retries before fallback
    output_schema_max_retries: int = int(os.getenv("GUARDRAIL_OUTPUT_SCHEMA_MAX_RETRIES", "2"))

    # DEV/TEST ONLY -- same stopgap pattern as OTP_DEBUG_LOG_ENABLED /
    # INVITE_DEBUG_LOG_ENABLED: logs every guardrail event (including
    # PASSED) to the console. Never rely on this as the real audit trail
    # -- that's agent_guardrail_logs (tenant DB) + reporting_db, wired up
    # in later milestones.
    guardrail_debug_log_enabled: bool = os.getenv("GUARDRAIL_DEBUG_LOG_ENABLED", "false").lower() == "true"


_cached: AgentServiceConfig | None = None


def get_config() -> AgentServiceConfig:
    global _cached
    if _cached is None:
        _cached = AgentServiceConfig()
    return _cached