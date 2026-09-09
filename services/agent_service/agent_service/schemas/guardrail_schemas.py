# LOCATION: services/agent_service/agent_service/schemas/guardrail_schemas.py

"""
Shared result types for the 5-layer GuardrailService (Section: GUARDRAILS
ARCHITECTURE). Every layer (input/output/bias/pii/behavioral) returns
`GuardrailCheckResult` objects; `GuardrailService` (guardrails/guardrail_service.py)
aggregates them and is the only place that builds the actual
`insynchire_events.schemas.GuardrailEvent` for logging/publishing --
this module deliberately does NOT redefine that schema (per the M6 task
brief: "reuse that existing schema, don't redefine it").

`action_taken` uses the exact same four values everywhere in the
codebase (agent_guardrail_logs.action_taken, GuardrailEvent.action_taken):
BLOCKED | SANITIZED | FLAGGED | PASSED.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

ActionTaken = Literal["BLOCKED", "SANITIZED", "FLAGGED", "PASSED"]


def hash_content(content: str) -> str:
    """SHA-256 hex digest -- used as `input_hash` so guardrail logs can
    correlate repeated triggers on the same input without persisting
    the raw content in every index/aggregate (Section 10g: guardrail
    logs store raw_flagged_content encrypted at the repository layer;
    the hash is safe to keep unencrypted for correlation)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class GuardrailCheckResult:
    """One outcome from one guardrail rule. `GuardrailService` collects
    a list of these per agent call and logs/publishes each one (Section:
    "No exceptions -- even PASSED events are sampled and logged")."""

    layer: int  # 1-5
    rule: str
    agent_name: str
    action_taken: ActionTaken
    trigger_reason: str
    raw_flagged_content: str = ""
    sanitized_value: Any = None
    input_hash: str = ""
    tenant_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not 1 <= self.layer <= 5:
            raise ValueError(f"layer must be 1-5, got {self.layer}")
        if not self.input_hash and self.raw_flagged_content:
            self.input_hash = hash_content(self.raw_flagged_content)


@dataclass
class InputGuardrailResult:
    """Aggregate result of running all Layer-1 rules on one piece of
    candidate-originated text for one agent call."""

    action: Literal["BLOCKED", "SANITIZED", "PASSED"]
    sanitized_text: str
    wrapped_text: str
    """`sanitized_text` wrapped in the mandatory <candidate_data> XML
    delimiter (Rule 1.4) -- this is what actually goes into the LLM
    prompt, never `sanitized_text` on its own."""
    events: list[GuardrailCheckResult]
    block_reason: str | None = None


@dataclass
class OutputGuardrailResult:
    """Aggregate result of running all Layer-2 rules against one agent's
    raw LLM output."""

    action: Literal["BLOCKED", "FLAGGED", "PASSED"]
    validated_output: Any | None
    """The Pydantic-validated (unknown fields dropped) output object, or
    None if BLOCKED / validation failed after retries."""
    events: list[GuardrailCheckResult]
    needs_retry: bool = False
    block_reason: str | None = None


@dataclass
class BiasScanResult:
    action: Literal["BLOCKED", "FLAGGED", "PASSED"]
    events: list[GuardrailCheckResult]
    flagged_fields: list[str] = field(default_factory=list)


@dataclass
class PIIScanResult:
    action: Literal["SANITIZED", "FLAGGED", "PASSED"]
    redacted_output: Any | None
    events: list[GuardrailCheckResult]


@dataclass
class FallbackDecision:
    """What `fallback_node` (Section: AGENTIC AI WORKFLOW) should do --
    built by the behavioral/fallback layer whenever an agent call can't
    proceed normally (guardrail block, retries exhausted, circuit
    breaker tripped, LLM timeout)."""

    triggered: bool
    reason: str
    interviewer_message: str = "AI suggestions temporarily unavailable"
    surface_to_candidate: bool = False  # Rule 5.1: NEVER True
    event: GuardrailCheckResult | None = None