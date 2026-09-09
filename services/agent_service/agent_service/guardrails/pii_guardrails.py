# LOCATION: services/agent_service/agent_service/guardrails/pii_guardrails.py

"""
LAYER 4 -- PII GUARDRAILS (Section: GUARDRAILS ARCHITECTURE).

Applied to: Report Synthesis Agent output (scorecard) before it's
stored or shown.

Rule 4.1 -- PII detection in scorecard (auto-redact + log; the
            redacted version is what's persisted -- raw is never stored)
Rule 4.2 -- No cross-candidate data leakage (evidence_citations must
            reference only the current session_id)
"""

from __future__ import annotations

import re
import uuid

from ..schemas.agent_io_schemas import Scorecard
from ..schemas.guardrail_schemas import GuardrailCheckResult, PIIScanResult
from .patterns import EMAIL_PATTERN, PHONE_PATTERN, UNIVERSITY_PATTERN

LAYER = 4

REDACTED_EMAIL = "[REDACTED_EMAIL]"
REDACTED_PHONE = "[REDACTED_PHONE]"
REDACTED_UNIVERSITY = "[REDACTED_UNIVERSITY]"
REDACTED_NAME = "the candidate"


def _redact_name(text: str, full_name: str | None) -> tuple[str, bool]:
    """Rule 4.1: 'candidate's full name (use "the candidate")'. Also
    catches a bare first-name-only mention, which is the more common
    way a name leaks into a generated narrative."""
    if not full_name:
        return text, False
    changed = False
    for candidate_name in {full_name, full_name.split()[0]} if " " in full_name else {full_name}:
        pattern = re.compile(re.escape(candidate_name), re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(REDACTED_NAME, text)
            changed = True
    return text, changed


def _redact_text_field(text: str, *, candidate_full_name: str | None) -> tuple[str, list[str]]:
    """Runs every Rule 4.1 detector against one text field. Returns the
    redacted text and a list of category names that were found/redacted
    (used to build the trigger_reason)."""
    found: list[str] = []

    redacted, name_changed = _redact_name(text, candidate_full_name)
    if name_changed:
        found.append("full_name")

    if EMAIL_PATTERN.search(redacted):
        redacted = EMAIL_PATTERN.sub(REDACTED_EMAIL, redacted)
        found.append("email")

    if PHONE_PATTERN.search(redacted):
        redacted = PHONE_PATTERN.sub(REDACTED_PHONE, redacted)
        found.append("phone")

    if UNIVERSITY_PATTERN.search(redacted):
        redacted = UNIVERSITY_PATTERN.sub(REDACTED_UNIVERSITY, redacted)
        found.append("university_in_scoring_context")

    return redacted, found


class PIIGuardrail:
    def redact_scorecard(
        self,
        scorecard: Scorecard,
        *,
        candidate_full_name: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> PIIScanResult:
        """Rule 4.1. Redacts every free-text field on a `Scorecard`
        (overall_summary, recommendation_rationale, each dimension's
        narrative) and returns a NEW Scorecard with the redacted text --
        Section: 'Scorecard DB record stores the redacted version — raw
        version never persisted,' so the caller must persist
        `redacted_output`, never the original `scorecard` passed in."""
        events: list[GuardrailCheckResult] = []
        all_found: set[str] = set()

        redacted_summary, found = _redact_text_field(
            scorecard.overall_summary, candidate_full_name=candidate_full_name
        )
        all_found.update(found)

        redacted_rationale, found = _redact_text_field(
            scorecard.recommendation_rationale, candidate_full_name=candidate_full_name
        )
        all_found.update(found)

        redacted_dimensions = {}
        for dim_name, dim in scorecard.dimensions.items():
            redacted_narrative, found = _redact_text_field(dim.narrative, candidate_full_name=candidate_full_name)
            all_found.update(found)
            redacted_dimensions[dim_name] = dim.model_copy(update={"narrative": redacted_narrative})

        redacted_scorecard = scorecard.model_copy(
            update={
                "overall_summary": redacted_summary,
                "recommendation_rationale": redacted_rationale,
                "dimensions": redacted_dimensions,
            }
        )

        if all_found:
            events.append(
                GuardrailCheckResult(
                    layer=LAYER,
                    rule="4.1_pii_detection_in_scorecard",
                    agent_name="report_synthesis",
                    action_taken="SANITIZED",
                    trigger_reason=f"redacted PII categories: {sorted(all_found)}",
                    raw_flagged_content="[raw content withheld from log -- see agent_guardrail_logs encrypted column]",
                    tenant_id=tenant_id,
                    session_id=scorecard.session_id,
                )
            )
            return PIIScanResult(action="SANITIZED", redacted_output=redacted_scorecard, events=events)

        events.append(
            GuardrailCheckResult(
                layer=LAYER,
                rule="4.0_pii_scan_passed",
                agent_name="report_synthesis",
                action_taken="PASSED",
                trigger_reason="no PII detected in scorecard text fields",
                tenant_id=tenant_id,
                session_id=scorecard.session_id,
            )
        )
        return PIIScanResult(action="PASSED", redacted_output=scorecard, events=events)

    def check_cross_candidate_leakage(
        self,
        *,
        agent_name: str,
        evidence_session_ids: list[uuid.UUID],
        current_session_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> PIIScanResult:
        """Rule 4.2. 'Report Synthesis Agent prompt must never contain
        data from a previous candidate's session — verified by checking
        that all evidence_citations reference session_ids matching the
        current session only.'"""
        events: list[GuardrailCheckResult] = []
        leaked = [sid for sid in evidence_session_ids if sid != current_session_id]

        if leaked:
            events.append(
                GuardrailCheckResult(
                    layer=LAYER,
                    rule="4.2_cross_candidate_leakage_check",
                    agent_name=agent_name,
                    action_taken="BLOCKED",
                    trigger_reason=(
                        f"evidence references {len(leaked)} session_id(s) other than the current "
                        f"session ({current_session_id}): {leaked}"
                    ),
                    tenant_id=tenant_id,
                    session_id=current_session_id,
                )
            )
            return PIIScanResult(action="FLAGGED", redacted_output=None, events=events)

        events.append(
            GuardrailCheckResult(
                layer=LAYER,
                rule="4.0_cross_candidate_leakage_passed",
                agent_name=agent_name,
                action_taken="PASSED",
                trigger_reason="all evidence references only the current session",
                tenant_id=tenant_id,
                session_id=current_session_id,
            )
        )
        return PIIScanResult(action="PASSED", redacted_output=None, events=events)