# LOCATION: services/agent_service/agent_service/tools/rag_question_retrieval_tool.py

"""
`rag_question_retrieval_tool` (Section: GRAPH 1 -- `question_strategist_node`
-- "rag_question_retrieval_tool(role, difficulty_target, topic_tags,
exclude_ids, embedding_model) → pgvector similarity search on
question_bank → returns top-5 candidate questions with similarity
scores").

*** INTERIM IMPLEMENTATION -- READ BEFORE MODIFYING ***
`question_bank` is a pgvector-backed tenant-DB table (Section: AGENT
MEMORY STRATEGY) that does not exist yet in this build order -- no
migration has created it, and no embedding model is wired in anywhere
in the codebase yet. Rather than block `question_strategist_node` on
that infrastructure (the exact same reasoning M6's
`rag_job_similarity_tool` and `job_service`'s `public_board_service`
already documented for their own interim stand-ins), this tool takes
an in-memory list of candidate questions (shaped like a `question_bank`
row) and ranks them by a simple topic-tag Jaccard-overlap score plus an
exact difficulty match bonus -- no embeddings, no LLM call.

When a real pgvector `question_bank` table exists, replace this
function's body with a real
`SELECT ... ORDER BY embedding <-> :query_vec LIMIT :top_k` call and
keep the same signature/return shape so `interview_graph.py` doesn't
need to change at the call site -- the exact migration path M6's
`find_similar_past_jobs` docstring already established.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CandidateQuestion:
    """Shape mirrors a `question_bank` row closely enough to stand in
    for a real query result (Section 5: `question_bank: question_id,
    title, body, difficulty, topic_tags[], language_tags[],
    test_cases (jsonb), ...`)."""

    question_id: str
    title: str
    body: str
    difficulty: str
    topic_tags: list[str]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def retrieve_candidate_questions(
    *,
    difficulty_target: str,
    topic_tags: list[str],
    exclude_ids: list[str] | None,
    question_pool: list[CandidateQuestion],
    top_k: int = 5,
) -> list[tuple[CandidateQuestion, float]]:
    """Returns up to `top_k` questions from `question_pool` (the
    in-memory stand-in for a real pgvector query result), each paired
    with a similarity score in [0, 1], sorted descending. Questions in
    `exclude_ids` (already asked this session) are never returned."""
    exclude_ids = set(exclude_ids or [])
    target_tags = {t.strip().lower() for t in topic_tags if t.strip()}

    scored: list[tuple[CandidateQuestion, float]] = []
    for question in question_pool:
        if question.question_id in exclude_ids:
            continue
        q_tags = {t.strip().lower() for t in question.topic_tags if t.strip()}
        score = _jaccard(target_tags, q_tags)
        if question.difficulty == difficulty_target:
            score = min(score + 0.5, 1.0)
        scored.append((question, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]