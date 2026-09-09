# LOCATION: services/agent_service/agent_service/guardrails/bias_guardrails.py

"""
LAYER 3 -- BIAS & FAIRNESS GUARDRAILS (Section: GUARDRAILS ARCHITECTURE).

Applied to: all free-text agent output (narratives, suggestions, scorecards).

Rule 3.1 -- Demographic language detection (BLOCKED, agent regenerates)
Rule 3.2 -- Comparative bias detection ("POTENTIAL_PROXY_BIAS", FLAGGED)
Rule 3.3 -- Consistency check across near-identical submissions (FLAGGED)
"""

from __future__ import annotations

import uuid
from collections import Counter

from ..schemas.guardrail_schemas import BiasScanResult, GuardrailCheckResult
from .patterns import DEMOGRAPHIC_TERM_PATTERNS, find_first_match

LAYER = 3


class BiasGuardrail:
    def scan_text_fields(
        self,
        *,
        agent_name: str,
        text_fields: dict[str, str],
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> BiasScanResult:
        """Rule 3.1. `text_fields` maps a field name (e.g.
        'overall_summary', 'evidence_narrative') to its text content.
        ANY match anywhere blocks the whole output -- Section: "Action:
        BLOCKED -- agent regenerates the output without the flagged
        content."""
        events: list[GuardrailCheckResult] = []
        flagged_fields: list[str] = []

        for field_name, text in text_fields.items():
            if not text:
                continue
            match = find_first_match(DEMOGRAPHIC_TERM_PATTERNS, text)
            if match is not None:
                flagged_fields.append(field_name)
                events.append(
                    GuardrailCheckResult(
                        layer=LAYER,
                        rule="3.1_demographic_language_detection",
                        agent_name=agent_name,
                        action_taken="BLOCKED",
                        trigger_reason=f"field '{field_name}' contains demographic-inference language: matched '{match.group(0)}'",
                        raw_flagged_content=text,
                        tenant_id=tenant_id,
                        session_id=session_id,
                    )
                )

        if events:
            return BiasScanResult(action="BLOCKED", events=events, flagged_fields=flagged_fields)

        events.append(
            GuardrailCheckResult(
                layer=LAYER,
                rule="3.0_bias_scan_passed",
                agent_name=agent_name,
                action_taken="PASSED",
                trigger_reason="no demographic language detected",
                tenant_id=tenant_id,
                session_id=session_id,
            )
        )
        return BiasScanResult(action="PASSED", events=events)

    def check_comparative_bias(
        self,
        *,
        agent_name: str,
        top_ranked_attribute_values: list[str],
        attribute_name: str,
        job_requirements_mention_attribute: bool,
        cluster_threshold: float = 0.8,
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> BiasScanResult:
        """Rule 3.2. `top_ranked_attribute_values` is the value of some
        non-skill attribute (e.g. university name) for each of the
        top-N ranked candidates. If `job_requirements_mention_attribute`
        is False and more than `cluster_threshold` of the top-ranked
        candidates share the SAME value, that's a proxy-bias signal
        (Section: "top-ranked candidates cluster by a non-skill
        attribute that correlates with demographic ... when job
        requirements don't mention it")."""
        events: list[GuardrailCheckResult] = []

        if job_requirements_mention_attribute or not top_ranked_attribute_values:
            events.append(
                GuardrailCheckResult(
                    layer=LAYER,
                    rule="3.0_comparative_bias_passed",
                    agent_name=agent_name,
                    action_taken="PASSED",
                    trigger_reason="attribute is job-relevant or no candidates to check",
                    tenant_id=tenant_id,
                    session_id=session_id,
                )
            )
            return BiasScanResult(action="PASSED", events=events)

        counts = Counter(top_ranked_attribute_values)
        most_common_value, most_common_count = counts.most_common(1)[0]
        cluster_ratio = most_common_count / len(top_ranked_attribute_values)

        if cluster_ratio >= cluster_threshold:
            events.append(
                GuardrailCheckResult(
                    layer=LAYER,
                    rule="3.2_comparative_bias_detection",
                    agent_name=agent_name,
                    action_taken="FLAGGED",
                    trigger_reason=(
                        f"POTENTIAL_PROXY_BIAS: {most_common_count}/{len(top_ranked_attribute_values)} "
                        f"top-ranked candidates share {attribute_name}='{most_common_value}', which is "
                        f"not mentioned in job requirements"
                    ),
                    raw_flagged_content=str(top_ranked_attribute_values),
                    tenant_id=tenant_id,
                    session_id=session_id,
                )
            )
            return BiasScanResult(action="FLAGGED", events=events, flagged_fields=[attribute_name])

        events.append(
            GuardrailCheckResult(
                layer=LAYER,
                rule="3.0_comparative_bias_passed",
                agent_name=agent_name,
                action_taken="PASSED",
                trigger_reason=f"no significant clustering on {attribute_name} (ratio={cluster_ratio:.2f})",
                tenant_id=tenant_id,
                session_id=session_id,
            )
        )
        return BiasScanResult(action="PASSED", events=events)

    def check_scoring_consistency(
        self,
        *,
        agent_name: str,
        similarity_score: float,
        score_a: float,
        score_b: float,
        max_score_delta: float = 1.0,
        similarity_threshold: float = 0.9,
        tenant_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> BiasScanResult:
        """Rule 3.3. `similarity_score` (0-1, computed upstream by
        whatever near-duplicate-solution detector the caller uses) and
        the two candidates' scores on the SAME question. Section:
        "Same question answered in statistically similar ways by two
        candidates should produce similar Code Analysis scores (±1 on
        a 5-point scale). If two nearly identical solutions score
        differently -> FLAGGED for human review.'"""
        events: list[GuardrailCheckResult] = []
        delta = abs(score_a - score_b)

        if similarity_score >= similarity_threshold and delta > max_score_delta:
            events.append(
                GuardrailCheckResult(
                    layer=LAYER,
                    rule="3.3_scoring_consistency_check",
                    agent_name=agent_name,
                    action_taken="FLAGGED",
                    trigger_reason=(
                        f"near-identical solutions (similarity={similarity_score:.2f}) scored "
                        f"{score_a} vs {score_b} (delta={delta} > {max_score_delta}); flagged for human review"
                    ),
                    tenant_id=tenant_id,
                    session_id=session_id,
                )
            )
            return BiasScanResult(action="FLAGGED", events=events)

        events.append(
            GuardrailCheckResult(
                layer=LAYER,
                rule="3.0_scoring_consistency_passed",
                agent_name=agent_name,
                action_taken="PASSED",
                trigger_reason="scores consistent for similarity level",
                tenant_id=tenant_id,
                session_id=session_id,
            )
        )
        return BiasScanResult(action="PASSED", events=events)