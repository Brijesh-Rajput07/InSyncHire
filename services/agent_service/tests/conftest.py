# LOCATION: services/agent_service/tests/conftest.py

"""Shared test helpers -- same conventions as every other service in
this repo: plain sync factory functions, async bodies wrapped in
asyncio.run() directly (no pytest-asyncio)."""

from __future__ import annotations

from agent_service.config import AgentServiceConfig
from agent_service.guardrails import GuardrailService


class FakePublisher:
    def __init__(self):
        self.published: list[tuple[str, object]] = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def build_test_config(**overrides) -> AgentServiceConfig:
    defaults = dict(
        input_length_limits={"code_analysis": 50, "question_strategist": 30, "report_synthesis": 200},
        circuit_breaker_max_triggers=3,
        circuit_breaker_window_seconds=60.0,
        circuit_breaker_cooldown_seconds=300.0,
        integrity_escalation_max_signals=3,
        integrity_escalation_window_seconds=1800.0,
        output_schema_max_retries=2,
        guardrail_debug_log_enabled=False,
    )
    defaults.update(overrides)
    return AgentServiceConfig(**defaults)


def build_guardrail_service(*, publish=None, config=None, debug_log=False) -> GuardrailService:
    return GuardrailService(config=config or build_test_config(), publish=publish, debug_log=debug_log)