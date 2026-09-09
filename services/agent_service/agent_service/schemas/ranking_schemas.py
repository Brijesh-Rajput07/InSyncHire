# LOCATION: services/agent_service/agent_service/schemas/ranking_schemas.py

"""
Input schemas for the AI Ranking Agent (Task J, Section: GRAPH 2 -- AI
RANKING GRAPH). Kept separate from `agent_io_schemas.py` because those
are OUTPUT schemas every agent's LLM call is validated against; these
are the INPUT shapes the graph itself is invoked with -- a job opening
and the pool of candidate profiles being ranked against it.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class JobOpeningInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: uuid.UUID
    title: str
    description: str
    skills_tags: list[str] = Field(default_factory=list)
    experience_level: str | None = None


class CandidateProfileInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: uuid.UUID
    skills: list[str] = Field(default_factory=list)
    experience_years: int | None = None
    bio: str = ""
    resume_text: str = ""
    university: str | None = None
    """Only ever used for the Rule 3.2 proxy-bias check (does the
    ranking cluster on this non-skill attribute?) -- NEVER passed to
    `profile_scorer_tool` and never allowed into an evidence_narrative
    (Rule 3.1 blocks it if a narrative somehow mentions it)."""