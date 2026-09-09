# LOCATION: shared/insynchire-events/insynchire_events/schemas.py

"""
Pydantic v2 schemas for every event that crosses the Kafka bus.

Every service imports these instead of building its own dicts. Fields are
intentionally explicit (no `dict[str, Any]` catch-alls for core data) so a
bad producer fails fast at publish time, not silently downstream in
Reporting Service.

`schema_version` on BaseEvent is bumped whenever a breaking change is made
to any event's shape. The goal is additive-only changes wherever possible.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .topics import Topics


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseEvent(BaseModel):
    """Common envelope fields present on every event in the system."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    schema_version: int = 1
    occurred_at: datetime = Field(default_factory=_utcnow)
    trace_id: str = Field(
        ..., description="Propagated from the originating request; ties logs across services."
    )
    tenant_id: uuid.UUID | None = Field(
        default=None,
        description="Null for global-scope events (e.g. tenant.signup_initiated pre-provisioning).",
    )
    actor_user_id: uuid.UUID | None = Field(
        default=None, description="Who caused this event, if applicable."
    )


# ─────────────────────────────────────────────────────────────────────────
# Tenant lifecycle
# ─────────────────────────────────────────────────────────────────────────

class TenantSignupInitiatedEvent(BaseEvent):
    tenant_id: uuid.UUID
    subdomain: str
    company_name: str
    company_domain: str
    created_by_user_id: uuid.UUID


class TenantCreatedEvent(BaseEvent):
    tenant_id: uuid.UUID
    subdomain: str
    company_domain: str
    plan: str = "trial"


class TenantSuspendedEvent(BaseEvent):
    tenant_id: uuid.UUID
    reason: str
    suspended_by: uuid.UUID | None = None


# ─────────────────────────────────────────────────────────────────────────
# Migration Service
# ─────────────────────────────────────────────────────────────────────────

class MigrationCompletedEvent(BaseEvent):
    tenant_id: uuid.UUID
    alembic_version: str
    applied_by_service: str = "migration_service"
    duration_ms: int


class MigrationFailedEvent(BaseEvent):
    tenant_id: uuid.UUID
    attempted_alembic_version: str
    error_message: str
    is_critical: bool = True


# ─────────────────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────────────────

class UserRegisteredEvent(BaseEvent):
    user_id: uuid.UUID
    email: str
    account_type: Literal["candidate", "company_user"]


class UserInvitedEvent(BaseEvent):
    invite_id: uuid.UUID
    email: str
    role: Literal["company_admin", "recruiter", "interviewer", "observer"]
    invited_by: uuid.UUID
    tenant_id: uuid.UUID


# ─────────────────────────────────────────────────────────────────────────
# Hiring pipeline
# ─────────────────────────────────────────────────────────────────────────

class JobPostedEvent(BaseEvent):
    tenant_id: uuid.UUID
    job_id: uuid.UUID
    org_id: uuid.UUID
    title: str
    posted_by: uuid.UUID


class ApplicationSubmittedEvent(BaseEvent):
    tenant_id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    candidate_user_id: uuid.UUID
    resume_id: uuid.UUID


class CandidateAdvancedEvent(BaseEvent):
    tenant_id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    candidate_user_id: uuid.UUID
    new_stage: str
    advanced_by: uuid.UUID


class CandidateRejectedEvent(BaseEvent):
    tenant_id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    candidate_user_id: uuid.UUID
    rejected_by: uuid.UUID
    reason: str | None = None


# ─────────────────────────────────────────────────────────────────────────
# Interview lifecycle
# ─────────────────────────────────────────────────────────────────────────

class InterviewScheduledEvent(BaseEvent):
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    application_id: uuid.UUID
    candidate_user_id: uuid.UUID
    interviewer_ids: list[uuid.UUID]
    observer_ids: list[uuid.UUID] = Field(default_factory=list)
    scheduled_at: datetime


class InterviewStartedEvent(BaseEvent):
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    started_at: datetime


class InterviewCompletedEvent(BaseEvent):
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    completed_at: datetime
    duration_seconds: int


class ScorecardGeneratedEvent(BaseEvent):
    tenant_id: uuid.UUID
    scorecard_id: uuid.UUID
    session_id: uuid.UUID
    candidate_user_id: uuid.UUID
    overall_recommendation: str
    is_final: bool


# ─────────────────────────────────────────────────────────────────────────
# Agent events (FIX-M0) -- added once the agent pipeline design (Section:
# AGENTIC AI WORKFLOW / GUARDRAILS ARCHITECTURE) caught up with this
# package. Purely additive: nothing above this section changed.
# ─────────────────────────────────────────────────────────────────────────

class GuardrailEvent(BaseEvent):
    """Structured record of one guardrail check outcome (Section:
    GUARDRAILS ARCHITECTURE — "Every guardrail trigger logged... no
    exceptions, even PASSED events are sampled and logged").

    Reused two ways: (1) as the Kafka payload for agent.guardrail_triggered
    (see AgentGuardrailTriggeredEvent below, which IS this schema), and
    (2) as a plain in-process data structure GuardrailService (M6) builds
    for every layer check before deciding whether to publish/persist it.
    """

    agent_name: str
    guardrail_layer: int  # 1-5, one of the 5 layers in GUARDRAILS ARCHITECTURE
    guardrail_rule: str
    input_hash: str
    trigger_reason: str
    raw_flagged_content: str
    # ^ Section 10g / Layer 4: PII/flagged content is encrypted before
    # persisting to tenant DB — that encryption happens at the
    # repository layer when this event is written to agent_guardrail_logs,
    # not in this schema. The Kafka payload itself still carries the
    # value in transit (Kafka topics are internal-network-only).
    action_taken: Literal["BLOCKED", "SANITIZED", "FLAGGED", "PASSED"]
    session_id: uuid.UUID | None = None

    @field_validator("guardrail_layer")
    @classmethod
    def _validate_layer_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("guardrail_layer must be between 1 and 5")
        return v


class AgentRankingCompletedEvent(BaseEvent):
    tenant_id: uuid.UUID
    job_id: uuid.UUID
    ranked_candidate_count: int


class AgentQuestionSuggestedEvent(BaseEvent):
    """Advisory only — human still approves (Kafka Topics section:
    "advisory — human still approves"). This event does not itself
    inject the question into the session."""

    tenant_id: uuid.UUID
    session_id: uuid.UUID
    question_id: uuid.UUID
    difficulty: str


class AgentCodeAnalyzedEvent(BaseEvent):
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    correctness_pct: float
    passed_tests: int
    failed_tests: int


class AgentIntegrityFlaggedEvent(BaseEvent):
    """No 'verdict'/'recommendation' field by design (GUARDRAILS
    ARCHITECTURE Rule 2.4: the Integrity Agent's output schema must not
    contain any field implying an auto-decision)."""

    tenant_id: uuid.UUID
    session_id: uuid.UUID
    signal_type: str
    confidence_score: float


class AgentScorecardReadyEvent(BaseEvent):
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    scorecard_id: uuid.UUID
    overall_recommendation: str


class AgentGuardrailTriggeredEvent(GuardrailEvent):
    """The Kafka payload for agent.guardrail_triggered -- literally IS a
    GuardrailEvent. Named separately only so the topic -> schema
    registry below has a distinctly-named class per Task A's wording;
    GuardrailEvent itself stays usable standalone wherever
    GuardrailService (M6) needs the structure without publishing it."""


# ─────────────────────────────────────────────────────────────────────────
# Cross-cutting error events
# ─────────────────────────────────────────────────────────────────────────

class ErrorCriticalEvent(BaseEvent):
    service_name: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ErrorWarningEvent(BaseEvent):
    service_name: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────
# Registry: topic -> schema. This is what lets publish()/subscribe()
# validate payloads without every service hardcoding the mapping.
# ─────────────────────────────────────────────────────────────────────────

EVENT_SCHEMA_REGISTRY: dict[str, type[BaseEvent]] = {
    Topics.TENANT_SIGNUP_INITIATED.value: TenantSignupInitiatedEvent,
    Topics.TENANT_CREATED.value: TenantCreatedEvent,
    Topics.TENANT_SUSPENDED.value: TenantSuspendedEvent,
    Topics.MIGRATION_COMPLETED.value: MigrationCompletedEvent,
    Topics.MIGRATION_FAILED.value: MigrationFailedEvent,
    Topics.USER_REGISTERED.value: UserRegisteredEvent,
    Topics.USER_INVITED.value: UserInvitedEvent,
    Topics.JOB_POSTED.value: JobPostedEvent,
    Topics.APPLICATION_SUBMITTED.value: ApplicationSubmittedEvent,
    Topics.CANDIDATE_ADVANCED.value: CandidateAdvancedEvent,
    Topics.CANDIDATE_REJECTED.value: CandidateRejectedEvent,
    Topics.INTERVIEW_SCHEDULED.value: InterviewScheduledEvent,
    Topics.INTERVIEW_STARTED.value: InterviewStartedEvent,
    Topics.INTERVIEW_COMPLETED.value: InterviewCompletedEvent,
    Topics.SCORECARD_GENERATED.value: ScorecardGeneratedEvent,
    Topics.AGENT_RANKING_COMPLETED.value: AgentRankingCompletedEvent,
    Topics.AGENT_QUESTION_SUGGESTED.value: AgentQuestionSuggestedEvent,
    Topics.AGENT_CODE_ANALYZED.value: AgentCodeAnalyzedEvent,
    Topics.AGENT_INTEGRITY_FLAGGED.value: AgentIntegrityFlaggedEvent,
    Topics.AGENT_SCORECARD_READY.value: AgentScorecardReadyEvent,
    Topics.AGENT_GUARDRAIL_TRIGGERED.value: AgentGuardrailTriggeredEvent,
    Topics.ERROR_CRITICAL.value: ErrorCriticalEvent,
    Topics.ERROR_WARNING.value: ErrorWarningEvent,
}


def schema_for_topic(topic: str) -> type[BaseEvent]:
    """Look up the Pydantic model registered for a topic.

    Raises KeyError if the topic has no registered schema — callers should
    treat that as a programming error (add the schema + registry entry),
    not something to silently swallow.
    """
    return EVENT_SCHEMA_REGISTRY[topic]
