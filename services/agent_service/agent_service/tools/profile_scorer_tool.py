# LOCATION: services/agent_service/agent_service/tools/profile_scorer_tool.py

"""
`profile_scorer_tool` (Section: GRAPH 2 -- AI RANKING GRAPH -- "structured
scoring of each candidate against job requirements (rule-based — not
LLM, to avoid bias amplification)").

This is the ONE place the actual numeric `match_score` is computed for
the AI Ranking Agent. It is deliberately pure/deterministic (no LLM
call, no randomness) so ranking outcomes are reproducible and auditable
-- Section 2's architecture-decision table: "Agent numeric scoring:
Rule-based (not LLM) for ranking scores -- Reduces bias amplification
vs LLM-scored ranking."

Scoring only ever looks at `skills` and `experience_years` -- it never
reads `bio`, `resume_text`, or `university` (Section 3.2's proxy-bias
concern exists precisely because attributes like university correlate
with demographics; keeping them entirely out of the scoring function is
a stronger guarantee than trying to catch bias after the fact).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..schemas.ranking_schemas import CandidateProfileInput, JobOpeningInput


@dataclass
class ScoredCandidate:
    user_id: uuid.UUID
    match_score: float  # 0-100
    matched_skills: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    confidence: float = 0.5  # 0-1


def score_candidate(
    job: JobOpeningInput,
    candidate: CandidateProfileInput,
    *,
    max_experience_bonus: float = 20.0,
    experience_points_per_year: float = 2.0,
) -> ScoredCandidate:
    """Rule-based scoring: skill overlap ratio (weighted 80%) plus a
    capped experience-years bonus (weighted to fill the remaining 20
    points). Both inputs are structural (lists/ints), never free text
    -- there is nothing here an LLM prompt-injection attempt could
    influence, since this function never sees `bio`/`resume_text`."""
    job_skills = {s.strip().lower() for s in job.skills_tags if s.strip()}
    candidate_skills = {s.strip().lower() for s in candidate.skills if s.strip()}

    matched = sorted(job_skills & candidate_skills)
    gaps = sorted(job_skills - candidate_skills)

    skill_ratio = (len(matched) / len(job_skills)) if job_skills else 0.0
    skill_component = skill_ratio * 80.0

    experience_bonus = min(
        (candidate.experience_years or 0) * experience_points_per_year, max_experience_bonus
    )

    match_score = round(min(skill_component + experience_bonus, 100.0), 1)

    # Confidence reflects how much signal we actually had to work with --
    # a job posting with no skills_tags at all gives a low-confidence
    # score regardless of the number, since skill_ratio is meaningless
    # against an empty set.
    confidence = 0.9 if job_skills else 0.3

    return ScoredCandidate(
        user_id=candidate.user_id,
        match_score=match_score,
        matched_skills=matched,
        gaps=gaps,
        confidence=confidence,
    )


def rank_candidates(
    job: JobOpeningInput, candidates: list[CandidateProfileInput]
) -> list[ScoredCandidate]:
    """Scores every candidate and returns them sorted by `match_score`
    descending (rank 1 = highest score). Ties are broken by `user_id`
    string order purely for deterministic output in tests -- this has
    no bearing on fairness since it only applies to exact score ties."""
    scored = [score_candidate(job, c) for c in candidates]
    scored.sort(key=lambda s: (-s.match_score, str(s.user_id)))
    return scored