# LOCATION: services/agent_service/tests/test_output_guardrails.py

import uuid

from agent_service.guardrails.output_guardrails import OutputGuardrail
from agent_service.schemas.agent_io_schemas import CodeAnalysisResult, RankedCandidate, RankingResult, Scorecard


def _guardrail(max_retries: int = 2) -> OutputGuardrail:
    return OutputGuardrail(max_retries=max_retries)


def _valid_code_analysis_dict(**overrides) -> dict:
    base = dict(correctness_pct=95.0, passed_tests=10, failed_tests=0, evidence_citations=["ev-1"])
    base.update(overrides)
    return base


def test_valid_output_passes():
    guardrail = _guardrail()
    result = guardrail.validate(
        agent_name="code_analysis", raw_output=_valid_code_analysis_dict(), schema_model=CodeAnalysisResult
    )
    assert result.action == "PASSED"
    assert isinstance(result.validated_output, CodeAnalysisResult)
    assert any(e.action_taken == "PASSED" for e in result.events)


def test_unknown_fields_are_dropped_not_rejected():
    guardrail = _guardrail()
    raw = _valid_code_analysis_dict()
    raw["some_field_the_llm_invented"] = "should be dropped silently"
    result = guardrail.validate(agent_name="code_analysis", raw_output=raw, schema_model=CodeAnalysisResult)
    assert result.action == "PASSED"
    assert not hasattr(result.validated_output, "some_field_the_llm_invented")


def test_missing_required_field_blocks_and_flags_retry():
    guardrail = _guardrail(max_retries=2)
    raw = {"passed_tests": 1, "failed_tests": 0}  # missing correctness_pct
    result = guardrail.validate(agent_name="code_analysis", raw_output=raw, schema_model=CodeAnalysisResult, retry_count=0)
    assert result.action == "BLOCKED"
    assert result.needs_retry is True
    assert result.validated_output is None


def test_missing_required_field_no_more_retries_after_max():
    guardrail = _guardrail(max_retries=2)
    raw = {"passed_tests": 1, "failed_tests": 0}
    result = guardrail.validate(agent_name="code_analysis", raw_output=raw, schema_model=CodeAnalysisResult, retry_count=2)
    assert result.action == "BLOCKED"
    assert result.needs_retry is False


def test_forbidden_field_on_integrity_blocks_entirely_even_with_valid_schema():
    """Rule 2.4: presence of a forbidden auto-decision field is a hard
    BLOCK regardless of what the schema itself would otherwise allow."""
    guardrail = _guardrail()
    raw = {
        "signal_type": "paste_burst", "confidence_score": 0.9, "raw_evidence": "evidence text",
        "verdict": "reject the candidate",  # forbidden -- must never reach state
    }
    from agent_service.schemas.agent_io_schemas import IntegritySignal

    result = guardrail.validate(agent_name="integrity", raw_output=raw, schema_model=IntegritySignal)
    assert result.action == "BLOCKED"
    forbidden_events = [e for e in result.events if e.rule == "2.4_forbidden_field_check"]
    assert len(forbidden_events) == 1
    assert "verdict" in forbidden_events[0].trigger_reason


def test_forbidden_field_hire_recommendation_on_code_analysis_blocks():
    guardrail = _guardrail()
    raw = _valid_code_analysis_dict()
    raw["hire_recommendation"] = "STRONG_YES"
    result = guardrail.validate(agent_name="code_analysis", raw_output=raw, schema_model=CodeAnalysisResult)
    assert result.action == "BLOCKED"
    assert result.events[0].rule == "2.4_forbidden_field_check"


def test_semantic_consistency_code_analysis_high_correctness_zero_passed_blocks():
    """Rule 2.2: correctness_pct > 80 but passed_tests == 0 contradicts
    the sandbox -- BLOCKED, trusting the sandbox."""
    guardrail = _guardrail()
    raw = _valid_code_analysis_dict(correctness_pct=95.0, passed_tests=0)
    result = guardrail.validate(agent_name="code_analysis", raw_output=raw, schema_model=CodeAnalysisResult, sandbox_passed_tests=0)
    assert result.action == "BLOCKED"
    assert any(e.rule == "2.2_semantic_consistency_code_analysis" for e in result.events)


def test_semantic_consistency_code_analysis_consistent_output_passes():
    guardrail = _guardrail()
    raw = _valid_code_analysis_dict(correctness_pct=95.0, passed_tests=10)
    result = guardrail.validate(agent_name="code_analysis", raw_output=raw, schema_model=CodeAnalysisResult, sandbox_passed_tests=10)
    assert result.action == "PASSED"


def test_semantic_consistency_ranking_flags_missing_skill_reference():
    guardrail = _guardrail()
    candidate_id = uuid.uuid4()
    raw = {
        "ranked_candidates": [
            {
                "user_id": str(candidate_id), "rank": 1, "match_score": 88.0,
                "evidence_narrative": "Strong communicator with leadership experience.",
                "matched_skills": ["python"], "gaps": [], "confidence": 0.9,
            }
        ]
    }
    result = guardrail.validate(
        agent_name="ranking", raw_output=raw, schema_model=RankingResult, job_requirement_skills=["python", "fastapi"]
    )
    assert result.action == "FLAGGED"
    assert any(e.rule == "2.2_semantic_consistency_ranking" for e in result.events)


def test_semantic_consistency_ranking_with_skill_reference_passes():
    guardrail = _guardrail()
    candidate_id = uuid.uuid4()
    raw = {
        "ranked_candidates": [
            {
                "user_id": str(candidate_id), "rank": 1, "match_score": 88.0,
                "evidence_narrative": "5 years of Python and FastAPI experience matching the role.",
                "matched_skills": ["python", "fastapi"], "gaps": [], "confidence": 0.9,
            }
        ]
    }
    result = guardrail.validate(
        agent_name="ranking", raw_output=raw, schema_model=RankingResult, job_requirement_skills=["python", "fastapi"]
    )
    assert result.action == "PASSED"


def test_semantic_consistency_report_synthesis_strong_yes_but_low_scores_flags():
    guardrail = _guardrail()
    session_id = uuid.uuid4()
    raw = {
        "session_id": str(session_id),
        "dimensions": {
            "problem_solving": {"score": 2, "evidence_citations": [], "narrative": "weak"},
            "code_quality": {"score": 2, "evidence_citations": [], "narrative": "weak"},
        },
        "overall_summary": "Candidate struggled overall.",
        "overall_recommendation": "STRONG_YES",
        "recommendation_rationale": "Despite low scores we recommend strongly.",
    }
    result = guardrail.validate(agent_name="report_synthesis", raw_output=raw, schema_model=Scorecard)
    assert result.action == "FLAGGED"
    assert any(e.rule == "2.2_semantic_consistency_report_synthesis" for e in result.events)


def test_hallucination_detection_flags_unverifiable_citation():
    guardrail = _guardrail()
    raw = _valid_code_analysis_dict(evidence_citations=["ev-1", "ev-does-not-exist"])
    result = guardrail.validate(
        agent_name="code_analysis", raw_output=raw, schema_model=CodeAnalysisResult, valid_evidence_ids={"ev-1"}
    )
    assert result.action == "FLAGGED"
    assert any(e.rule == "2.3_hallucination_detection" for e in result.events)


def test_hallucination_detection_passes_when_all_citations_verifiable():
    guardrail = _guardrail()
    raw = _valid_code_analysis_dict(evidence_citations=["ev-1", "ev-2"])
    result = guardrail.validate(
        agent_name="code_analysis", raw_output=raw, schema_model=CodeAnalysisResult,
        valid_evidence_ids={"ev-1", "ev-2", "ev-3"},
    )
    assert result.action == "PASSED"