# LOCATION: services/agent_service/agent_service/guardrails/output_guardrails.py

"""
LAYER 2 -- OUTPUT GUARDRAILS (Section: GUARDRAILS ARCHITECTURE).

Applied after every agent's LLM call, before `state.update()`.

Rule 2.1 -- Pydantic schema enforcement (unknown fields dropped; missing
            required fields -> retry, then fallback)
Rule 2.2 -- Semantic consistency checks (per named agent)
Rule 2.3 -- Hallucination detection (citations must reference real evidence)
Rule 2.4 -- Forbidden field check (auto-decision fields -> BLOCKED entirely)
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ValidationError

from ..schemas.guardrail_schemas import GuardrailCheckResult, OutputGuardrailResult

LAYER = 2

# Rule 2.4 -- fields that would imply the agent made an auto-decision.
# Presence of ANY of these keys anywhere in the raw LLM output for the
# named agent is a hard BLOCK, regardless of what schema validation
# would otherwise do with them (Section: "If the LLM somehow generates
# text containing these in a way that implies auto-action -> BLOCKED
# entirely").
FORBIDDEN_OUTPUT_FIELDS: dict[str, set[str]] = {
    "integrity": {"verdict", "decision", "recommendation", "reject", "auto_reject", "should_reject"},
    "code_analysis": {"hire_recommendation", "verdict", "decision"},
}


def _find_forbidden_fields(agent_name: str, raw_output: dict[str, Any]) -> set[str]:
    forbidden = FORBIDDEN_OUTPUT_FIELDS.get(agent_name, set())
    if not forbidden:
        return set()
    return {k for k in raw_output.keys() if k in forbidden}


def _drop_unknown_fields(raw_output: dict[str, Any], schema_model: type[BaseModel]) -> dict[str, Any]:
    """Rule 2.1: 'Fields that don't exist in the schema are DROPPED (not
    passed through)'. We deliberately do NOT rely on Pydantic's
    `extra="forbid"` for this (our agent_io_schemas models use
    extra="forbid" specifically so Rule 2.4's forbidden-field check --
    which runs first, on the raw dict -- can't be silently bypassed by
    constructing the model directly); instead we filter down to known
    field names ourselves before validating."""
    known_fields = set(schema_model.model_fields.keys())
    return {k: v for k, v in raw_output.items() if k in known_fields}


class OutputGuardrail:
    def __init__(self, *, max_retries: int = 2):
        self._max_retries = max_retries

    def _check_forbidden_fields(
        self, agent_name: str, raw_output: dict[str, Any], *, tenant_id, session_id
    ) -> GuardrailCheckResult | None:
        forbidden_found = _find_forbidden_fields(agent_name, raw_output)
        if not forbidden_found:
            return None
        return GuardrailCheckResult(
            layer=LAYER,
            rule="2.4_forbidden_field_check",
            agent_name=agent_name,
            action_taken="BLOCKED",
            trigger_reason=f"output contained forbidden auto-decision field(s): {sorted(forbidden_found)}",
            raw_flagged_content=str({k: raw_output[k] for k in forbidden_found}),
            tenant_id=tenant_id,
            session_id=session_id,
        )

    def _validate_pydantic_schema(
        self, agent_name: str, raw_output: dict[str, Any], schema_model: type[BaseModel], *, tenant_id, session_id
    ) -> tuple[BaseModel | None, GuardrailCheckResult | None]:
        cleaned = _drop_unknown_fields(raw_output, schema_model)
        try:
            validated = schema_model.model_validate(cleaned)
            return validated, None
        except ValidationError as exc:
            event = GuardrailCheckResult(
                layer=LAYER,
                rule="2.1_pydantic_schema_enforcement",
                agent_name=agent_name,
                action_taken="BLOCKED",
                trigger_reason=f"output failed schema validation (missing/invalid required fields): {exc.errors()[:3]}",
                raw_flagged_content=str(raw_output)[:500],
                tenant_id=tenant_id,
                session_id=session_id,
            )
            return None, event

    def _semantic_consistency_check(
        self,
        agent_name: str,
        validated: BaseModel,
        *,
        sandbox_passed_tests: int | None,
        job_requirement_skills: list[str] | None,
        tenant_id,
        session_id,
    ) -> GuardrailCheckResult | None:
        """Rule 2.2 -- agent-specific consistency rules named explicitly
        in the project plan."""
        if agent_name == "code_analysis":
            correctness_pct = getattr(validated, "correctness_pct", None)
            passed_tests = getattr(validated, "passed_tests", None)
            # "if correctness_pct > 80 but passed_tests == 0 (sandbox
            # results contradict LLM assessment) -> BLOCKED, log
            # inconsistency, trust sandbox results over LLM narrative."
            effective_passed = sandbox_passed_tests if sandbox_passed_tests is not None else passed_tests
            if correctness_pct is not None and correctness_pct > 80 and effective_passed == 0:
                return GuardrailCheckResult(
                    layer=LAYER,
                    rule="2.2_semantic_consistency_code_analysis",
                    agent_name=agent_name,
                    action_taken="BLOCKED",
                    trigger_reason=(
                        f"correctness_pct={correctness_pct} contradicts sandbox passed_tests="
                        f"{effective_passed}; trusting sandbox results over LLM narrative"
                    ),
                    raw_flagged_content=validated.model_dump_json(),
                    tenant_id=tenant_id,
                    session_id=session_id,
                )

        if agent_name == "ranking" and job_requirement_skills:
            # "if evidence_narrative doesn't reference any skill from the
            # job requirements -> FLAGGED, returned to agent for
            # regeneration."
            flagged_candidates = []
            for candidate in getattr(validated, "ranked_candidates", []):
                narrative_lower = candidate.evidence_narrative.lower()
                if not any(skill.lower() in narrative_lower for skill in job_requirement_skills):
                    flagged_candidates.append(str(candidate.user_id))
            if flagged_candidates:
                return GuardrailCheckResult(
                    layer=LAYER,
                    rule="2.2_semantic_consistency_ranking",
                    agent_name=agent_name,
                    action_taken="FLAGGED",
                    trigger_reason=(
                        f"evidence_narrative for candidate(s) {flagged_candidates} references no "
                        f"job-requirement skill; returned for regeneration"
                    ),
                    raw_flagged_content=validated.model_dump_json(),
                    tenant_id=tenant_id,
                    session_id=session_id,
                )

        if agent_name == "report_synthesis":
            # "if overall_recommendation == STRONG_YES but all dimension
            # scores are below 3/5 -> FLAGGED for human review."
            overall = getattr(validated, "overall_recommendation", None)
            dimensions = getattr(validated, "dimensions", None) or {}
            if overall == "STRONG_YES" and dimensions and all(d.score < 3 for d in dimensions.values()):
                return GuardrailCheckResult(
                    layer=LAYER,
                    rule="2.2_semantic_consistency_report_synthesis",
                    agent_name=agent_name,
                    action_taken="FLAGGED",
                    trigger_reason="overall_recommendation=STRONG_YES but every dimension score is below 3/5",
                    raw_flagged_content=validated.model_dump_json(),
                    tenant_id=tenant_id,
                    session_id=session_id,
                )

        return None

    def _hallucination_check(
        self,
        agent_name: str,
        validated: BaseModel,
        *,
        valid_evidence_ids: set[str] | None,
        tenant_id,
        session_id,
    ) -> GuardrailCheckResult | None:
        """Rule 2.3 -- "Any specific claim in agent output that
        references a timestamp, test case number, or code line that
        doesn't exist in the state evidence -> FLAGGED." We check
        `evidence_citations` (present on CodeAnalysisResult, RankedCandidate
        via evidence_narrative isn't structured enough to check here,
        and Scorecard) against the caller-supplied set of citation IDs
        that actually exist in the session's evidence."""
        if valid_evidence_ids is None:
            return None
        citations = getattr(validated, "evidence_citations", None)
        if not citations:
            return None
        unverifiable = [c for c in citations if c not in valid_evidence_ids]
        if not unverifiable:
            return None
        return GuardrailCheckResult(
            layer=LAYER,
            rule="2.3_hallucination_detection",
            agent_name=agent_name,
            action_taken="FLAGGED",
            trigger_reason=f"evidence_citations reference IDs not present in session evidence: {unverifiable}",
            raw_flagged_content=str(citations),
            tenant_id=tenant_id,
            session_id=session_id,
        )

    def validate(
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
    ) -> OutputGuardrailResult:
        events: list[GuardrailCheckResult] = []

        # Rule 2.4 runs FIRST, on the raw dict, before any field-dropping
        # or schema coercion could hide a forbidden field's presence.
        forbidden_event = self._check_forbidden_fields(
            agent_name, raw_output, tenant_id=tenant_id, session_id=session_id
        )
        if forbidden_event is not None:
            events.append(forbidden_event)
            return OutputGuardrailResult(
                action="BLOCKED", validated_output=None, events=events, block_reason=forbidden_event.trigger_reason
            )

        # Rule 2.1
        validated, schema_event = self._validate_pydantic_schema(
            agent_name, raw_output, schema_model, tenant_id=tenant_id, session_id=session_id
        )
        if schema_event is not None:
            events.append(schema_event)
            needs_retry = retry_count < self._max_retries
            return OutputGuardrailResult(
                action="BLOCKED",
                validated_output=None,
                events=events,
                needs_retry=needs_retry,
                block_reason=schema_event.trigger_reason,
            )

        assert validated is not None

        # Rule 2.2
        consistency_event = self._semantic_consistency_check(
            agent_name, validated,
            sandbox_passed_tests=sandbox_passed_tests,
            job_requirement_skills=job_requirement_skills,
            tenant_id=tenant_id, session_id=session_id,
        )
        if consistency_event is not None:
            events.append(consistency_event)

        # Rule 2.3
        hallucination_event = self._hallucination_check(
            agent_name, validated, valid_evidence_ids=valid_evidence_ids, tenant_id=tenant_id, session_id=session_id
        )
        if hallucination_event is not None:
            events.append(hallucination_event)

        if any(e.action_taken == "BLOCKED" for e in events):
            block_reason = next(e.trigger_reason for e in events if e.action_taken == "BLOCKED")
            return OutputGuardrailResult(action="BLOCKED", validated_output=None, events=events, block_reason=block_reason)

        if events:
            return OutputGuardrailResult(action="FLAGGED", validated_output=validated, events=events)

        events.append(
            GuardrailCheckResult(
                layer=LAYER,
                rule="2.0_output_passed",
                agent_name=agent_name,
                action_taken="PASSED",
                trigger_reason="no output guardrail rule triggered",
                tenant_id=tenant_id,
                session_id=session_id,
            )
        )
        return OutputGuardrailResult(action="PASSED", validated_output=validated, events=events)