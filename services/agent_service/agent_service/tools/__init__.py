# LOCATION: services/agent_service/agent_service/tools/__init__.py

"""LangGraph tool functions used by agent nodes.

Graph 2 (M6): `rag_job_similarity_tool`, `profile_scorer_tool`.
Graph 1 (M10): `sandbox_execution_tool` (mocked, flagged),
`complexity_analysis_tool`, `difficulty_calibration_tool`,
`rag_question_retrieval_tool` (interim in-memory stand-in),
`fetch_code_snapshots_tool` (real data, thin formatter --
`interview_service` owns the repository),
`fetch_session_transcript_tool` (gap flagged, always unavailable).
"""

from .profile_scorer_tool import ScoredCandidate, rank_candidates, score_candidate
from .rag_job_similarity_tool import find_similar_past_jobs
from .sandbox_execution_tool import run_in_sandbox
from .complexity_analysis_tool import analyze_complexity
from .difficulty_calibration_tool import calibrate_difficulty
from .rag_question_retrieval_tool import CandidateQuestion, retrieve_candidate_questions
from .fetch_code_snapshots_tool import CodeSnapshotRecord, build_code_history_summary
from .fetch_session_transcript_tool import fetch_session_transcript

__all__ = [
    "ScoredCandidate", "score_candidate", "rank_candidates", "find_similar_past_jobs",
    "run_in_sandbox", "analyze_complexity", "calibrate_difficulty",
    "CandidateQuestion", "retrieve_candidate_questions",
    "CodeSnapshotRecord", "build_code_history_summary",
    "fetch_session_transcript",
]