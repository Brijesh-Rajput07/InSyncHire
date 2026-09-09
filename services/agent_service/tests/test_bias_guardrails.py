# LOCATION: services/agent_service/tests/test_bias_guardrails.py

from agent_service.guardrails.bias_guardrails import BiasGuardrail


def test_clean_text_passes():
    guardrail = BiasGuardrail()
    result = guardrail.scan_text_fields(
        agent_name="report_synthesis",
        text_fields={"overall_summary": "Demonstrated strong problem-solving and clear communication."},
    )
    assert result.action == "PASSED"


def test_demographic_language_blocks_and_flags_field():
    guardrail = BiasGuardrail()
    result = guardrail.scan_text_fields(
        agent_name="report_synthesis",
        text_fields={"overall_summary": "A young candidate who communicated well."},
    )
    assert result.action == "BLOCKED"
    assert "overall_summary" in result.flagged_fields
    assert any(e.rule == "3.1_demographic_language_detection" for e in result.events)


def test_gender_pronoun_blocks():
    guardrail = BiasGuardrail()
    result = guardrail.scan_text_fields(
        agent_name="report_synthesis",
        text_fields={"narrative": "He solved the problem quickly."},
    )
    assert result.action == "BLOCKED"


def test_multiple_fields_all_scanned_and_flagged():
    guardrail = BiasGuardrail()
    result = guardrail.scan_text_fields(
        agent_name="report_synthesis",
        text_fields={
            "field_a": "This candidate has a strong accent.",
            "field_b": "Clean, professional narrative with no issues.",
        },
    )
    assert result.action == "BLOCKED"
    assert result.flagged_fields == ["field_a"]


def test_comparative_bias_flags_clustering_on_irrelevant_attribute():
    guardrail = BiasGuardrail()
    result = guardrail.check_comparative_bias(
        agent_name="ranking",
        top_ranked_attribute_values=["Ivy University", "Ivy University", "Ivy University", "State College"],
        attribute_name="university",
        job_requirements_mention_attribute=False,
        cluster_threshold=0.7,
    )
    assert result.action == "FLAGGED"
    assert "POTENTIAL_PROXY_BIAS" in result.events[0].trigger_reason


def test_comparative_bias_passes_when_attribute_is_job_relevant():
    guardrail = BiasGuardrail()
    result = guardrail.check_comparative_bias(
        agent_name="ranking",
        top_ranked_attribute_values=["Ivy University"] * 4,
        attribute_name="university",
        job_requirements_mention_attribute=True,
        cluster_threshold=0.7,
    )
    assert result.action == "PASSED"


def test_comparative_bias_passes_with_no_clustering():
    guardrail = BiasGuardrail()
    result = guardrail.check_comparative_bias(
        agent_name="ranking",
        top_ranked_attribute_values=["A University", "B University", "C University", "D University"],
        attribute_name="university",
        job_requirements_mention_attribute=False,
        cluster_threshold=0.7,
    )
    assert result.action == "PASSED"


def test_scoring_consistency_flags_divergent_scores_on_similar_solutions():
    guardrail = BiasGuardrail()
    result = guardrail.check_scoring_consistency(
        agent_name="code_analysis", similarity_score=0.95, score_a=5, score_b=2,
    )
    assert result.action == "FLAGGED"
    assert any(e.rule == "3.3_scoring_consistency_check" for e in result.events)


def test_scoring_consistency_passes_for_similar_scores():
    guardrail = BiasGuardrail()
    result = guardrail.check_scoring_consistency(
        agent_name="code_analysis", similarity_score=0.95, score_a=4, score_b=5,
    )
    assert result.action == "PASSED"


def test_scoring_consistency_passes_for_dissimilar_solutions_even_with_score_gap():
    guardrail = BiasGuardrail()
    result = guardrail.check_scoring_consistency(
        agent_name="code_analysis", similarity_score=0.2, score_a=5, score_b=1,
    )
    assert result.action == "PASSED"