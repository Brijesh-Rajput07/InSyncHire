# LOCATION: services/agent_service/agent_service/schemas/interview_io_schemas.py

"""
M10 -- output shapes for Graph 1's tools (Section: AGENTIC AI WORKFLOW,
GRAPH 1 -- INTERVIEW PIPELINE GRAPH). Kept separate from
`agent_io_schemas.py` (agent NODE outputs, validated by the output
guardrail) and `ranking_schemas.py` (Graph 2 inputs) because these are
plain TOOL return shapes -- never themselves passed through
`OutputGuardrail.validate()`, since a tool result isn't an LLM output
that could hallucinate/misbehave in the ways Layer 2 guards against
(sandbox execution and complexity analysis are deterministic/rule-based
per Section 10a and the "profile_scorer_tool ... rule-based, not LLM"
precedent from M6). They're consumed BY the LLM-calling nodes as
additional context.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SandboxExecutionResult(BaseModel):
    """Output of `sandbox_execution_tool` (Section: "sandbox_execution_tool
    ... runs in Piston/Judge0, returns {stdout, stderr, passed_tests,
    failed_tests, execution_time_ms, memory_used_mb}").

    *** INTERIM / MOCKED -- see tools/sandbox_execution_tool.py's module
    docstring. This milestone does NOT execute candidate code anywhere,
    on the app server or otherwise (Section 10a: "NEVER exec/eval/
    subprocess candidate code on app server"). Wiring a real Piston/
    Judge0 sandbox is explicitly out of scope here pending explicit
    confirmation -- this schema exists so `code_analysis_node`'s
    guardrail-facing shape (Rule 2.2's semantic-consistency check needs
    `sandbox_passed_tests`) is already correct once a real sandbox is
    plugged in behind this exact interface."""

    model_config = ConfigDict(extra="forbid")

    stdout: str = ""
    stderr: str = ""
    passed_tests: int = Field(..., ge=0)
    failed_tests: int = Field(..., ge=0)
    execution_time_ms: int = Field(..., ge=0)
    memory_used_mb: float = Field(..., ge=0)
    mocked: bool = True
    """True whenever this result did NOT come from a real sandbox --
    always True until a real Piston/Judge0 integration replaces
    `tools/sandbox_execution_tool.py`'s body. Callers (code_analysis_node)
    surface this on agent_decision_logs so it's never confused with a
    real execution result during an audit."""


class ComplexityAnalysisResult(BaseModel):
    """Output of `complexity_analysis_tool` (Section: "static analysis:
    time/space complexity estimate, style issues"). Rule-based (regex/
    AST heuristics), never an LLM call -- same "deterministic tool,
    not LLM" precedent as `profile_scorer_tool` (M6)."""

    model_config = ConfigDict(extra="forbid")

    time_complexity_estimate: str = "unknown"
    space_complexity_estimate: str = "unknown"
    style_issues: list[str] = Field(default_factory=list)
    line_count: int = Field(..., ge=0)


class DifficultyCalibrationResult(BaseModel):
    """Output of `difficulty_calibration_tool` (Section:
    "determines appropriate next difficulty level based on performance").
    Rule-based on the running average of `CodeAnalysisResult.correctness_pct`
    across the session's `question_history` -- never an LLM call, so a
    candidate's code content can never influence which difficulty is
    picked via prompt injection."""

    model_config = ConfigDict(extra="forbid")

    recommended_difficulty: str
    rationale: str
    average_correctness_pct: float | None = None


class TranscriptFetchResult(BaseModel):
    """Output of `fetch_session_transcript_tool` (Section:
    "fetch_session_transcript_tool(session_id) → chat + any STT
    transcript"). *** GAP FLAGGED, NOT FAKED *** -- M9's WebSocket
    gateway relays chat but does not persist it (no `chat_messages`
    table exists yet). Until a FIX-M9 adds real chat persistence, this
    tool always returns `available=False` with an empty transcript
    rather than fabricating transcript content -- see
    `tools/fetch_session_transcript_tool.py`'s module docstring."""

    model_config = ConfigDict(extra="forbid")

    available: bool
    transcript_text: str = ""
    message_count: int = 0
    gap_reason: str | None = None