# LOCATION: shared/insynchire-events/insynchire_events/topics.py

"""
Canonical Kafka topic names.

Use `Topics.<NAME>.value` everywhere instead of hardcoded strings — this
is the single source of truth matching the Kafka Topics section of the
project plan. Adding a topic here also requires adding a matching entry
to `schemas.EVENT_SCHEMA_REGISTRY` in schemas.py so consumers can
validate incoming payloads.
"""

from __future__ import annotations

from enum import Enum


class Topics(str, Enum):
    TENANT_SIGNUP_INITIATED = "tenant.signup_initiated"
    TENANT_CREATED = "tenant.created"
    TENANT_SUSPENDED = "tenant.suspended"

    MIGRATION_COMPLETED = "migration.completed"
    MIGRATION_FAILED = "migration.failed"

    USER_REGISTERED = "user.registered"
    USER_INVITED = "user.invited"

    JOB_POSTED = "job.posted"
    APPLICATION_SUBMITTED = "application.submitted"
    CANDIDATE_ADVANCED = "candidate.advanced"
    CANDIDATE_REJECTED = "candidate.rejected"

    INTERVIEW_SCHEDULED = "interview.scheduled"
    INTERVIEW_STARTED = "interview.started"
    INTERVIEW_COMPLETED = "interview.completed"

    SCORECARD_GENERATED = "scorecard.generated"

    # Agent events (FIX-M0 -- added when the agent pipeline design
    # caught up with the events package; additive only, nothing above changed)
    AGENT_RANKING_COMPLETED = "agent.ranking_completed"
    AGENT_QUESTION_SUGGESTED = "agent.question_suggested"
    AGENT_CODE_ANALYZED = "agent.code_analyzed"
    AGENT_INTEGRITY_FLAGGED = "agent.integrity_flagged"
    AGENT_SCORECARD_READY = "agent.scorecard_ready"
    AGENT_GUARDRAIL_TRIGGERED = "agent.guardrail_triggered"

    ERROR_CRITICAL = "error.critical"
    ERROR_WARNING = "error.warning"

    @property
    def dlq(self) -> str:
        """Dead-letter topic name for this topic."""
        return f"{self.value}.dlq"

    @classmethod
    def all_topics(cls) -> list[str]:
        return [t.value for t in cls]
