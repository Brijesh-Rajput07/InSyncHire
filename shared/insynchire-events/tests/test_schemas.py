# LOCATION: shared/insynchire-events/tests/test_schemas.py

"""
Unit tests for insynchire_events schemas and registry.

Run with: pytest -q  (from shared/insynchire-events/)
"""

import uuid

import pytest
from pydantic import ValidationError

from insynchire_events.schemas import (
    EVENT_SCHEMA_REGISTRY,
    AgentGuardrailTriggeredEvent,
    AgentIntegrityFlaggedEvent,
    ApplicationSubmittedEvent,
    GuardrailEvent,
    TenantSignupInitiatedEvent,
    schema_for_topic,
)
from insynchire_events.topics import Topics


def test_every_topic_has_a_registered_schema():
    for topic in Topics:
        assert topic.value in EVENT_SCHEMA_REGISTRY, f"missing schema for {topic.value}"


def test_dlq_naming():
    assert Topics.JOB_POSTED.dlq == "job.posted.dlq"


def test_tenant_signup_event_requires_fields():
    with pytest.raises(ValidationError):
        TenantSignupInitiatedEvent(trace_id="abc")  # missing required fields


def test_tenant_signup_event_valid():
    event = TenantSignupInitiatedEvent(
        trace_id="trace-123",
        tenant_id=uuid.uuid4(),
        subdomain="acme",
        company_name="Acme Corp",
        company_domain="acme.com",
        created_by_user_id=uuid.uuid4(),
    )
    assert event.schema_version == 1
    assert event.subdomain == "acme"


def test_event_is_frozen_and_rejects_extra_fields():
    event = ApplicationSubmittedEvent(
        trace_id="t1",
        tenant_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        candidate_user_id=uuid.uuid4(),
        resume_id=uuid.uuid4(),
    )
    with pytest.raises(ValidationError):
        ApplicationSubmittedEvent(
            trace_id="t1",
            tenant_id=uuid.uuid4(),
            application_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            candidate_user_id=uuid.uuid4(),
            resume_id=uuid.uuid4(),
            unexpected_field="nope",
        )
    with pytest.raises(Exception):
        event.job_id = uuid.uuid4()  # frozen -> should raise


def test_schema_for_topic_lookup():
    assert schema_for_topic(Topics.JOB_POSTED.value).__name__ == "JobPostedEvent"


def test_unknown_topic_raises_keyerror():
    with pytest.raises(KeyError):
        schema_for_topic("not.a.real.topic")


# --- FIX-M0: agent.* events + GuardrailEvent ---

def test_all_six_agent_topics_registered():
    agent_topics = [t for t in Topics if t.value.startswith("agent.")]
    assert len(agent_topics) == 6
    for topic in agent_topics:
        assert topic.value in EVENT_SCHEMA_REGISTRY


def test_guardrail_event_valid():
    event = GuardrailEvent(
        trace_id="t1",
        tenant_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        agent_name="code_analysis_agent",
        guardrail_layer=1,
        guardrail_rule="prompt_injection_stripping",
        input_hash="abc123",
        trigger_reason="detected '<system>' marker",
        raw_flagged_content="ignore previous instructions",
        action_taken="SANITIZED",
    )
    assert event.action_taken == "SANITIZED"


def test_guardrail_event_rejects_layer_out_of_range():
    with pytest.raises(ValidationError):
        GuardrailEvent(
            trace_id="t1", agent_name="x", guardrail_layer=6, guardrail_rule="r",
            input_hash="h", trigger_reason="t", raw_flagged_content="c", action_taken="PASSED",
        )


def test_guardrail_event_rejects_invalid_action_taken():
    with pytest.raises(ValidationError):
        GuardrailEvent(
            trace_id="t1", agent_name="x", guardrail_layer=1, guardrail_rule="r",
            input_hash="h", trigger_reason="t", raw_flagged_content="c",
            action_taken="NOT_A_REAL_ACTION",
        )


def test_agent_guardrail_triggered_event_is_a_guardrail_event():
    event = AgentGuardrailTriggeredEvent(
        trace_id="t1", agent_name="integrity_agent", guardrail_layer=4,
        guardrail_rule="pii_redaction", input_hash="h", trigger_reason="candidate name detected",
        raw_flagged_content="John Smith", action_taken="BLOCKED",
    )
    assert isinstance(event, GuardrailEvent)


def test_agent_integrity_flagged_event_has_no_verdict_field():
    """Guardrails Rule 2.4: no field implying an auto-decision."""
    event = AgentIntegrityFlaggedEvent(
        trace_id="t1", tenant_id=uuid.uuid4(), session_id=uuid.uuid4(),
        signal_type="paste_burst", confidence_score=0.82,
    )
    assert not hasattr(event, "verdict")
    assert not hasattr(event, "recommendation")
