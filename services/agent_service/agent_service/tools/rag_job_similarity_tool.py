# LOCATION: services/agent_service/agent_service/tools/rag_job_similarity_tool.py

"""
`rag_job_similarity_tool` (Section: GRAPH 2 -- AI RANKING GRAPH --
"pgvector search for similar past job openings and their successful
hire profiles (if historical data exists)").

*** INTERIM IMPLEMENTATION -- READ BEFORE MODIFYING ***
The project plan specifies this does a real pgvector similarity search
against `question_bank`/`successful_hire_profiles` embeddings in the
tenant DB (Section: AGENT MEMORY STRATEGY -- "question_bank embeddings
in pgvector (per tenant DB)"). That infrastructure (pgvector-backed
tenant tables, an embedding model, a RAG retrieval pipeline) doesn't
exist yet in this build order -- it's introduced incrementally starting
around M8-M11 as the live interview pipeline needs it too. Rather than
block the AI Ranking Agent on infrastructure several milestones away
(the same reasoning `job_service/services/public_board_service.py`
documented for the interim public job board), this implementation
computes a lightweight Jaccard similarity over `skills_tags` between
the current job opening and any `historical_jobs` the caller supplies.

This satisfies the SPIRIT of the tool at the call-site boundary
(`ranking_agent_node` calls `find_similar_past_jobs(...)`, gets back a
ranked list of similar past jobs, exactly as if pgvector had answered)
but is NOT a real semantic/embedding search -- when pgvector-backed
`question_bank`/`successful_hire_profiles` tables exist, replace this
function's body with a real `SELECT ... ORDER BY embedding <-> :query_vec`
call and keep the same signature so `ranking_graph.py` doesn't change.

Section: "if historical data exists" is handled gracefully here too --
an empty or missing `historical_jobs` list just returns an empty
result, which is the correct behavior for a brand-new tenant with no
job history yet (this is NOT an error case).
"""

from __future__ import annotations

from ..schemas.ranking_schemas import JobOpeningInput


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def find_similar_past_jobs(
    job: JobOpeningInput,
    historical_jobs: list[JobOpeningInput] | None,
    *,
    top_k: int = 5,
) -> list[tuple[JobOpeningInput, float]]:
    """Returns up to `top_k` historical jobs most similar to `job`,
    each paired with a similarity score in [0, 1], sorted descending.
    Returns an empty list if there's no history to compare against."""
    if not historical_jobs:
        return []

    job_skills = {s.strip().lower() for s in job.skills_tags if s.strip()}
    scored: list[tuple[JobOpeningInput, float]] = []
    for past_job in historical_jobs:
        past_skills = {s.strip().lower() for s in past_job.skills_tags if s.strip()}
        similarity = _jaccard_similarity(job_skills, past_skills)
        scored.append((past_job, similarity))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]