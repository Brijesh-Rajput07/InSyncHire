# LOCATION: services/agent_service/agent_service/guardrails/guardrail_service.py

"""
GuardrailService -- the single class that wraps every agent node call
(Section 11: "Every agent node follows this structure -- no exceptions").

Owns instances of all 5 layers plus the Layer-5 stateful trackers
(circuit breaker, integrity escalation) and is the ONE place that turns
an internal `GuardrailCheckResult` into the shared
`insynchire_events.schemas.GuardrailEvent` for logging + publishing to
`agent.guardrail_triggered` (Section: "Every guardrail trigger logged.
No exceptions -- even PASSED events are sampled and logged").

This milestone (M6) does not yet persist to `agent_guardrail_logs`
(tenant DB) -- that's wired up once this service has a live
TenantResolver + tenant DB session, same pattern as tenant_service /
job_service (see `provision_agent_service_persistence` docstring below
for the intended M10 integration point). `publish` is optional and
defaults to a no-op so this service is fully testable without Kafka.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from ..config import AgentServiceConfig, get_config
from ..schemas.guardrail_schemas import (
    BiasScanResult,
    FallbackDecision,
    GuardrailCheckResult,
    InputGuardrailResult,
    OutputGuardrailResult,
    PIIScanResult,
)
from ..schemas.agent_io_schemas import Scorecard
from .behavioral_guardrails import (
    CircuitBreaker,
    FallbackHandler,
    HumanApprovalTimeoutPolicy,
    IntegrityEscalationTracker,
)
from .bias_guardrails import BiasGuardrail
from .input_guardrails import InputGuardrail
from .output_guardrails import OutputGuardrail
from .pii_guardrails import PIIGuardrail

logger = logging.getLogger("agent_service.guardrails")

PublishFn = Callable[[str, Any], Awaitable[None]]

# Matches insynchire_events.topics.Topics.AGENT_GUARDRAIL_TRIGGERED.value --
# not imported directly so this package doesn't hard-require
# insynchire-events to be installed just to construct a GuardrailService
# (only `log_and_publish` needs it, and does the import lazily).
AGENT_GUARDRAIL_TRIGGERED_TOPIC = "agent.guardrail_triggered"


def node_key_for(*, tenant_id: uuid.UUID | None, session_id: uuid.UUID | None, node_name: str) -> str:
    """Canonical circuit-breaker / escalation-tracker key -- one place
    this string is built so callers never accidentally use two
    different formats for what should be the same key."""
    return f"{tenant_id}:{session_id}:{node_name}"


class GuardrailService:
    def __init__(
        self,
        *,
        config: AgentServiceConfig | None = None,
        publish: PublishFn | None = None,
        debug_log: bool | None = None,
    ):
        self._config = config or get_config()
        self._publish = publish
        self._debug_log = self._config.guardrail_debug_log_enabled if debug_log is None else debug_log

        self.input_guardrail = InputGuardrail(length_limits=self._config.input_length_limits)
        self.output_guardrail = OutputGuardrail(max_retries=self._config.output_schema_max_retries)
        self.bias_guardrail = BiasGuardrail()
        self.pii_guardrail = PIIGuardrail()
        self.circuit_breaker = CircuitBreaker(
            max_triggers=self._config.circuit_breaker_max_triggers,
            window_seconds=self._config.circuit_breaker_window_seconds,
            cooldown_seconds=self._config.circuit_breaker_cooldown_seconds,
        )
        self.integrity_escalation = IntegrityEscalationTracker(
            max_signals=self._config.integrity_escalation_max_signals,
            window_seconds=self._config.integrity_escalation_window_seconds,
        )
        self.fallback_handler = FallbackHandler()
        self.timeout_policy = HumanApprovalTimeoutPolicy()

        # In-process record of every event this instance has logged --
        # not a substitute for agent_guardrail_logs/reporting_db, just
        # makes the service trivially testable/inspectable without a
        # DB or Kafka in the loop.
        self.logged_events: list[GuardrailCheckResult] = []

    # ── Layer 1 ──────────────────────────────────────────────────────
    async def validate_input(
        self,
        *,
        agent_name: str,
        text: str,
        raw_input: dict[str, Any] | None = None,
        schema_model: type[BaseModel] | None = None,
        data_type: str = "text",
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        trace_id: str = "unset",
    ) -> InputGuardrailResult:
        result = self.input_guardrail.validate(
            agent_name=agent_name, text=text, raw_input=raw_input, schema_model=schema_model,
            data_type=data_type, tenant_id=tenant_id, session_id=session_id,
        )
        await self._log_events(result.events, trace_id=trace_id)
        return result

    # ── Layer 2 ──────────────────────────────────────────────────────
    async def validate_output(
        self,
        *,
        agent_name: str,
        raw_output: dict[str, Any],
        schema_model: type[BaseModel],
        retry_count: int = 0,
        sandbox_passed_tests: int | None = None,
        job_requirement_skills: list[str] | None = None,
        valid_evidence_ids: set[str] | None = None,
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        trace_id: str = "unset",
    ) -> OutputGuardrailResult:
        result = self.output_guardrail.validate(
            agent_name=agent_name, raw_output=raw_output, schema_model=schema_model, retry_count=retry_count,
            sandbox_passed_tests=sandbox_passed_tests, job_requirement_skills=job_requirement_skills,
            valid_evidence_ids=valid_evidence_ids, tenant_id=tenant_id, session_id=session_id,
        )
        await self._log_events(result.events, trace_id=trace_id)
        return result

    # ── Layer 3 ──────────────────────────────────────────────────────
    async def bias_scan(
        self,
        *,
        agent_name: str,
        text_fields: dict[str, str],
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        trace_id: str = "unset",
    ) -> BiasScanResult:
        result = self.bias_guardrail.scan_text_fields(
            agent_name=agent_name, text_fields=text_fields, tenant_id=tenant_id, session_id=session_id
        )
        await self._log_events(result.events, trace_id=trace_id)
        return result

    # ── Layer 4 ──────────────────────────────────────────────────────
    async def pii_scan(
        self,
        scorecard: Scorecard,
        *,
        candidate_full_name: str | None = None,
        tenant_id: uuid.UUID | None = None,
        trace_id: str = "unset",
    ) -> PIIScanResult:
        result = self.pii_guardrail.redact_scorecard(
            scorecard, candidate_full_name=candidate_full_name, tenant_id=tenant_id
        )
        await self._log_events(result.events, trace_id=trace_id)
        return result

    # ── Layer 5 ──────────────────────────────────────────────────────
    async def check_and_record_circuit_breaker(
        self,
        *,
        agent_name: str,
        tenant_id: uuid.UUID | None,
        session_id: uuid.UUID | None,
        node_name: str,
        trace_id: str = "unset",
    ) -> FallbackDecision | None:
        """Call once per node invocation. Returns a `FallbackDecision`
        (already logged) if this invocation trips (or is currently
        under) the circuit breaker; returns None if the node may
        proceed normally."""
        key = node_key_for(tenant_id=tenant_id, session_id=session_id, node_name=node_name)
        if self.circuit_breaker.is_tripped(key):
            decision = self.fallback_handler.build_circuit_breaker_trip(
                agent_name=agent_name, node_key=key,
                cooldown_seconds=self._config.circuit_breaker_cooldown_seconds,
                tenant_id=tenant_id, session_id=session_id,
            )
            await self._log_events([decision.event], trace_id=trace_id)
            return decision

        just_tripped = self.circuit_breaker.record_trigger(key)
        if just_tripped:
            decision = self.fallback_handler.build_circuit_breaker_trip(
                agent_name=agent_name, node_key=key,
                cooldown_seconds=self._config.circuit_breaker_cooldown_seconds,
                tenant_id=tenant_id, session_id=session_id,
            )
            await self._log_events([decision.event], trace_id=trace_id)
            return decision

        return None

    async def record_integrity_signal(
        self,
        *,
        session_id: uuid.UUID,
        agent_name: str = "integrity",
        tenant_id: uuid.UUID | None = None,
        trace_id: str = "unset",
    ) -> bool:
        """Rule 5.4. Returns True if this signal pushed the session over
        the escalation threshold -- caller (M10's orchestrator_node)
        should route to human_approval_node with type='INTEGRITY_REVIEW'."""
        should_escalate = self.integrity_escalation.record_signal(str(session_id))
        if should_escalate:
            event = GuardrailCheckResult(
                layer=5,
                rule="5.4_integrity_flag_escalation",
                agent_name=agent_name,
                action_taken="FLAGGED",
                trigger_reason=(
                    f"integrity signal count for session {session_id} exceeded "
                    f"{self._config.integrity_escalation_max_signals} within "
                    f"{self._config.integrity_escalation_window_seconds:.0f}s -- escalating to human review"
                ),
                tenant_id=tenant_id,
                session_id=session_id,
            )
            await self._log_events([event], trace_id=trace_id)
        return should_escalate

    async def trigger_fallback(
        self,
        *,
        agent_name: str,
        reason: str,
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        trace_id: str = "unset",
    ) -> FallbackDecision:
        """Rule 5.1. Call whenever an agent call cannot proceed:
        upstream guardrail BLOCKED, retries exhausted, or an LLM
        timeout/unhandled exception."""
        decision = self.fallback_handler.build(
            agent_name=agent_name, reason=reason, tenant_id=tenant_id, session_id=session_id
        )
        await self._log_events([decision.event], trace_id=trace_id)
        return decision

    # ── Logging / publishing ─────────────────────────────────────────
    async def _log_events(self, events: list[GuardrailCheckResult], *, trace_id: str) -> None:
        for event in events:
            self.logged_events.append(event)

            if self._debug_log:
                logger.info(
                    "[GUARDRAIL] layer=%s rule=%s agent=%s action=%s reason=%s",
                    event.layer, event.rule, event.agent_name, event.action_taken, event.trigger_reason,
                )

            if self._publish is not None:
                guardrail_event = self._to_guardrail_event(event, trace_id=trace_id)
                await self._publish(AGENT_GUARDRAIL_TRIGGERED_TOPIC, guardrail_event)

    @staticmethod
    def _to_guardrail_event(result: GuardrailCheckResult, *, trace_id: str):
        """Builds the SHARED `insynchire_events.schemas.GuardrailEvent`
        (via its `AgentGuardrailTriggeredEvent` subclass, the registered
        schema for `agent.guardrail_triggered`) from our internal
        `GuardrailCheckResult`. Imported lazily so constructing a
        `GuardrailService` never requires `insynchire-events` to be
        installed unless `publish` is actually provided."""
        from insynchire_events.schemas import AgentGuardrailTriggeredEvent

        return AgentGuardrailTriggeredEvent(
            trace_id=trace_id,
            tenant_id=result.tenant_id,
            agent_name=result.agent_name,
            guardrail_layer=result.layer,
            guardrail_rule=result.rule,
            input_hash=result.input_hash or "",
            trigger_reason=result.trigger_reason,
            raw_flagged_content=result.raw_flagged_content,
            action_taken=result.action_taken,
            session_id=result.session_id,
        )


# ─────────────────────────────────────────────────────────────────────
# Section 11 -- generic agent-node wrapper pattern.
#
# This is the concrete implementation of the pseudocode in the project
# plan's "Guardrails quick-reference (for generating any agent code)"
# section, generalized so any future agent node (M10's interview
# pipeline nodes, M6's own AI Ranking Agent node) can call it instead
# of re-deriving the wrapper each time.
# ─────────────────────────────────────────────────────────────────────

LLMCallFn = Callable[[str], Awaitable[dict[str, Any]]]
"""Takes the wrapped (<candidate_data>-delimited) prompt text, returns
the raw (not-yet-validated) LLM output as a dict."""


async def run_guarded_agent_node(
    *,
    guardrail_service: GuardrailService,
    agent_name: str,
    node_name: str,
    candidate_text: str,
    schema_model: type[BaseModel],
    llm_call: LLMCallFn,
    build_prompt: Callable[[str], str] | None = None,
    raw_input: dict[str, Any] | None = None,
    input_schema_model: type[BaseModel] | None = None,
    text_fields_for_bias_scan: Callable[[BaseModel], dict[str, str]] | None = None,
    sandbox_passed_tests: int | None = None,
    job_requirement_skills: list[str] | None = None,
    valid_evidence_ids: set[str] | None = None,
    tenant_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    trace_id: str = "unset",
) -> BaseModel | FallbackDecision:
    """Runs one agent node through all 5 guardrail layers, exactly per
    Section 11's wrapper:

      1. LAYER 1 input guardrails -- BLOCKED -> fallback immediately.
      2. Circuit breaker check (Layer 5, Rule 5.2) -- tripped -> fallback.
      3. The actual LLM call, with candidate data wrapped in
         <candidate_data> (never raw).
      4. LAYER 2 output guardrails, with a bounded retry loop
         (Rule 2.1) -- exhausted -> fallback.
      5. LAYER 3 bias scan on free-text output fields (if a field
         extractor was supplied) -- BLOCKED -> fallback.
      6. LAYER 4 PII scan is intentionally NOT run here -- it's scoped
         to Report Synthesis / Scorecard output only (Section: "Applied
         to: Report Synthesis Agent output"), so callers building that
         specific node call `guardrail_service.pii_scan()` directly
         after this returns.

    Returns either the validated (and possibly bias-flagged-but-passed)
    output model, or a `FallbackDecision` if any layer could not be
    satisfied -- callers route to `[fallback_node]` in that case,
    exactly as the LangGraph spec describes.
    """
    # LAYER 1
    input_result = await guardrail_service.validate_input(
        agent_name=agent_name, text=candidate_text, raw_input=raw_input, schema_model=input_schema_model,
        tenant_id=tenant_id, session_id=session_id, trace_id=trace_id,
    )
    if input_result.action == "BLOCKED":
        return await guardrail_service.trigger_fallback(
            agent_name=agent_name, reason=f"input guardrail blocked: {input_result.block_reason}",
            tenant_id=tenant_id, session_id=session_id, trace_id=trace_id,
        )

    # Rule 5.2 circuit breaker
    breaker_decision = await guardrail_service.check_and_record_circuit_breaker(
        agent_name=agent_name, tenant_id=tenant_id, session_id=session_id, node_name=node_name, trace_id=trace_id,
    )
    if breaker_decision is not None:
        return breaker_decision

    prompt = build_prompt(input_result.wrapped_text) if build_prompt else input_result.wrapped_text

    # LAYER 2 with bounded retry (Rule 2.1)
    retry_count = 0
    output_result: OutputGuardrailResult | None = None
    while retry_count <= guardrail_service.output_guardrail._max_retries:  # noqa: SLF001 -- internal, same module family
        raw_output = await llm_call(prompt)
        output_result = await guardrail_service.validate_output(
            agent_name=agent_name, raw_output=raw_output, schema_model=schema_model, retry_count=retry_count,
            sandbox_passed_tests=sandbox_passed_tests, job_requirement_skills=job_requirement_skills,
            valid_evidence_ids=valid_evidence_ids, tenant_id=tenant_id, session_id=session_id, trace_id=trace_id,
        )
        if output_result.action != "BLOCKED" or not output_result.needs_retry:
            break
        retry_count += 1

    assert output_result is not None
    if output_result.action == "BLOCKED":
        return await guardrail_service.trigger_fallback(
            agent_name=agent_name, reason=f"output guardrail blocked after retries: {output_result.block_reason}",
            tenant_id=tenant_id, session_id=session_id, trace_id=trace_id,
        )

    validated_output = output_result.validated_output
    assert validated_output is not None

    # LAYER 3 (only if the caller told us which fields are free text)
    if text_fields_for_bias_scan is not None:
        bias_result = await guardrail_service.bias_scan(
            agent_name=agent_name, text_fields=text_fields_for_bias_scan(validated_output),
            tenant_id=tenant_id, session_id=session_id, trace_id=trace_id,
        )
        if bias_result.action == "BLOCKED":
            return await guardrail_service.trigger_fallback(
                agent_name=agent_name,
                reason=f"bias guardrail blocked fields {bias_result.flagged_fields}",
                tenant_id=tenant_id, session_id=session_id, trace_id=trace_id,
            )

    return validated_output