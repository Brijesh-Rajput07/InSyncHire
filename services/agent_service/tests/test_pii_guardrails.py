# LOCATION: services/agent_service/tests/test_pii_guardrails.py

import uuid

from agent_service.guardrails.pii_guardrails import PIIGuardrail
from agent_service.schemas.agent_io_schemas import DimensionScore, Scorecard


def _scorecard(**overrides) -> Scorecard:
    session_id = overrides.pop("session_id", uuid.uuid4())
    base = dict(
        session_id=session_id,
        dimensions={
            "problem_solving": DimensionScore(score=4, evidence_citations=["ev-1"], narrative="Solid approach."),
        },
        overall_summary="Strong candidate overall.",
        overall_recommendation="YES",
        recommendation_rationale="Consistent performance across dimensions.",
    )
    base.update(overrides)
    return Scorecard(**base)


def test_clean_scorecard_passes_untouched():
    guardrail = PIIGuardrail()
    scorecard = _scorecard()
    result = guardrail.redact_scorecard(scorecard)
    assert result.action == "PASSED"
    assert result.redacted_output.overall_summary == scorecard.overall_summary


def test_full_name_redacted_to_the_candidate():
    guardrail = PIIGuardrail()
    scorecard = _scorecard(overall_summary="Jane Doe demonstrated excellent debugging skills.")
    result = guardrail.redact_scorecard(scorecard, candidate_full_name="Jane Doe")
    assert result.action == "SANITIZED"
    assert "Jane Doe" not in result.redacted_output.overall_summary
    assert "the candidate" in result.redacted_output.overall_summary
    assert "full_name" in result.events[0].trigger_reason


def test_email_redacted():
    guardrail = PIIGuardrail()
    scorecard = _scorecard(recommendation_rationale="Contact at jane.doe@example.com for follow-up.")
    result = guardrail.redact_scorecard(scorecard)
    assert result.action == "SANITIZED"
    assert "jane.doe@example.com" not in result.redacted_output.recommendation_rationale
    assert "[REDACTED_EMAIL]" in result.redacted_output.recommendation_rationale


def test_phone_redacted():
    guardrail = PIIGuardrail()
    scorecard = _scorecard(overall_summary="Reachable at 415-555-0199 anytime.")
    result = guardrail.redact_scorecard(scorecard)
    assert result.action == "SANITIZED"
    assert "415-555-0199" not in result.redacted_output.overall_summary
    assert "[REDACTED_PHONE]" in result.redacted_output.overall_summary


def test_university_in_dimension_narrative_redacted():
    guardrail = PIIGuardrail()
    scorecard = _scorecard(
        dimensions={
            "problem_solving": DimensionScore(
                score=4, evidence_citations=[], narrative="Graduate of Stanford University with strong fundamentals."
            )
        }
    )
    result = guardrail.redact_scorecard(scorecard)
    assert result.action == "SANITIZED"
    assert "Stanford University" not in result.redacted_output.dimensions["problem_solving"].narrative
    assert "[REDACTED_UNIVERSITY]" in result.redacted_output.dimensions["problem_solving"].narrative


def test_raw_output_never_persisted_only_redacted_returned():
    """Section 4.1: 'raw version never persisted' -- the caller must
    use `redacted_output`, and the original `scorecard` object passed
    in must remain unmodified (guardrails never mutate in place)."""
    guardrail = PIIGuardrail()
    original = _scorecard(overall_summary="Contact jane@example.com")
    result = guardrail.redact_scorecard(original)
    assert original.overall_summary == "Contact jane@example.com"  # untouched
    assert "jane@example.com" not in result.redacted_output.overall_summary


def test_cross_candidate_leakage_passes_when_all_sessions_match():
    guardrail = PIIGuardrail()
    session_id = uuid.uuid4()
    result = guardrail.check_cross_candidate_leakage(
        agent_name="report_synthesis", evidence_session_ids=[session_id, session_id], current_session_id=session_id
    )
    assert result.action == "PASSED"


def test_cross_candidate_leakage_flags_foreign_session_id():
    guardrail = PIIGuardrail()
    current_session = uuid.uuid4()
    other_session = uuid.uuid4()
    result = guardrail.check_cross_candidate_leakage(
        agent_name="report_synthesis",
        evidence_session_ids=[current_session, other_session],
        current_session_id=current_session,
    )
    assert result.action == "FLAGGED"
    assert str(other_session) in result.events[0].trigger_reason