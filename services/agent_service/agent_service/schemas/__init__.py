# LOCATION: services/agent_service/agent_service/schemas/__init__.py

"""Pydantic/dataclass schemas for the Agent Service: guardrail result
types (guardrail_schemas.py) and example agent output models
(agent_io_schemas.py) used to exercise them."""

from .agent_io_schemas import (
    CodeAnalysisResult,
    CoPilotSuggestion,
    DimensionScore,
    IntegritySignal,
    RankedCandidate,
    RankingResult,
    Scorecard,
    SuggestedQuestion,
)
from .guardrail_schemas import (
    ActionTaken,
    BiasScanResult,
    FallbackDecision,
    GuardrailCheckResult,
    InputGuardrailResult,
    OutputGuardrailResult,
    PIIScanResult,
    hash_content,
)
from .ranking_schemas import CandidateProfileInput, JobOpeningInput

__all__ = [
    "CodeAnalysisResult", "SuggestedQuestion", "IntegritySignal", "CoPilotSuggestion",
    "RankedCandidate", "RankingResult", "DimensionScore", "Scorecard",
    "ActionTaken", "GuardrailCheckResult", "InputGuardrailResult", "OutputGuardrailResult",
    "BiasScanResult", "PIIScanResult", "FallbackDecision", "hash_content",
    "JobOpeningInput", "CandidateProfileInput",
]