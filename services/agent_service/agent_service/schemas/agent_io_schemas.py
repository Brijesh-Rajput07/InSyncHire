# LOCATION: services/agent_service/agent_service/schemas/agent_io_schemas.py

"""
Pydantic output models for the agent nodes described in the project
plan's AGENTIC AI WORKFLOW section. These are the "strict Pydantic
output model" every agent's LLM call is validated against (Layer 2,
Rule 2.1) and the concrete types the rest of this milestone's guardrail
layers are unit-tested against.

Field sets are the minimum needed to exercise every named guardrail
rule (Section 2.2-2.4, 3.1-3.3, 4.1-4.2) -- later milestones (M10, M11)
that build the real LangGraph nodes should extend these, not replace
them, so the guardrail rules written against them keep working.

Deliberately excluded fields, per the plan's own guardrail rules:
  - IntegritySignal has NO `verdict`/`decision`/`recommendation`/`reject`
    field (Rule 2.4) -- `pydantic.ConfigDict(extra="forbid")` makes it
    impossible for a caller to sneak one in even by dict-construction.
  - CodeAnalysisResult has NO `hire_recommendation` field (Rule 2.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CodeAnalysisResult(BaseModel):
    """Output of the Code Analysis Agent node."""

    model_config = ConfigDict(extra="forbid")

    correctness_pct: float = Field(..., ge=0, le=100)
    passed_tests: int = Field(..., ge=0)
    failed_tests: int = Field(..., ge=0)
    complexity_estimate: str | None = None
    style_issues: list[str] = Field(default_factory=list)
    edge_cases_missed: list[str] = Field(default_factory=list)
    evidence_citations: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)


class SuggestedQuestion(BaseModel):
    """Output of the Question Strategist Agent node -- advisory only,
    routes to human_approval_node before ever reaching the candidate."""

    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    title: str
    body: str
    difficulty: str
    rationale: str
    topic_tags: list[str] = Field(default_factory=list)
    difficulty_rationale: str | None = None
    estimated_completion_mins: int | None = None


class IntegritySignal(BaseModel):
    """Output of the Integrity Agent node. NO field named "verdict",
    "decision", "recommendation", or "reject" exists here (Rule 2.4) --
    `extra="forbid"` means Pydantic itself rejects any attempt to add
    one via `.model_validate()`, not just at the type-checker level."""

    model_config = ConfigDict(extra="forbid")

    signal_type: str
    confidence_score: float = Field(..., ge=0, le=1)
    raw_evidence: str
    timestamp: datetime = Field(default_factory=_utcnow)
    false_positive_notes: str | None = None
    recommended_human_action: str | None = None
    session_id: uuid.UUID | None = None


class CoPilotSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_followup: str | None = None
    probing_prompts: list[str] = Field(default_factory=list)
    hint_for_stuck_candidate: str | None = None
    concept_explanation: str | None = None
    confidence: float = Field(..., ge=0, le=1)
    based_on: list[str] = Field(default_factory=list)


class RankedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    rank: int
    match_score: float = Field(..., ge=0, le=100)
    evidence_narrative: str
    matched_skills: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)


class RankingResult(BaseModel):
    """Output of the AI Ranking Agent node. `evidence_narrative` on
    each candidate must not reference name/location/demographic
    signals (Section: GRAPH 2 -- AI RANKING GRAPH) -- enforced by the
    bias guardrail layer, not by this schema."""

    model_config = ConfigDict(extra="forbid")

    ranked_candidates: list[RankedCandidate]
    generated_at: datetime = Field(default_factory=_utcnow)


class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(..., ge=1, le=5)
    evidence_citations: list[str] = Field(default_factory=list)
    narrative: str


class Scorecard(BaseModel):
    """Output of the Report Synthesis Agent node."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    dimensions: dict[str, DimensionScore]
    integrity_summary: dict[str, int] = Field(default_factory=dict)
    overall_summary: str
    overall_recommendation: Literal["STRONG_YES", "YES", "NO", "STRONG_NO"]
    recommendation_rationale: str
    generated_at: datetime = Field(default_factory=_utcnow)
    approved_by: uuid.UUID | None = None
    is_final: bool = False
    evidence_citations: list[str] = Field(default_factory=list)
    """Session IDs referenced by evidence, for Rule 4.2's cross-candidate
    leakage check -- normally implicit in `dimensions[*].evidence_citations`,
    surfaced flat here so the PII guardrail can check it directly."""