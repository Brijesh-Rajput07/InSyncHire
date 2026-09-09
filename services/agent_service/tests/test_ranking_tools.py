# LOCATION: services/agent_service/tests/test_ranking_tools.py

import uuid

from agent_service.schemas.ranking_schemas import CandidateProfileInput, JobOpeningInput
from agent_service.tools import find_similar_past_jobs, rank_candidates, score_candidate


def _job(**overrides) -> JobOpeningInput:
    base = dict(job_id=uuid.uuid4(), title="Backend Engineer", description="Build APIs", skills_tags=["python", "fastapi", "postgres"])
    base.update(overrides)
    return JobOpeningInput(**base)


def _candidate(**overrides) -> CandidateProfileInput:
    base = dict(user_id=uuid.uuid4(), skills=["python", "fastapi"], experience_years=3, bio="Experienced backend dev.")
    base.update(overrides)
    return CandidateProfileInput(**base)


def test_score_candidate_full_skill_match_scores_highly():
    job = _job()
    candidate = _candidate(skills=["python", "fastapi", "postgres"], experience_years=5)
    result = score_candidate(job, candidate)
    assert result.matched_skills == ["fastapi", "postgres", "python"]
    assert result.gaps == []
    assert result.match_score >= 90


def test_score_candidate_partial_match_reflects_gaps():
    job = _job()
    candidate = _candidate(skills=["python"], experience_years=0)
    result = score_candidate(job, candidate)
    assert result.matched_skills == ["python"]
    assert set(result.gaps) == {"fastapi", "postgres"}
    assert 0 < result.match_score < 50


def test_score_candidate_never_reads_bio_or_university():
    """Rule 3.2 concern: scoring must be purely structural."""
    job = _job()
    candidate_a = _candidate(bio="", university=None)
    candidate_b = _candidate(
        user_id=candidate_a.user_id, skills=candidate_a.skills, experience_years=candidate_a.experience_years,
        bio="A completely different, very long biography mentioning many things.",
        university="Some University",
    )
    result_a = score_candidate(job, candidate_a)
    result_b = score_candidate(job, candidate_b)
    assert result_a.match_score == result_b.match_score
    assert result_a.matched_skills == result_b.matched_skills


def test_score_candidate_empty_job_skills_gives_low_confidence_and_experience_only_score():
    job = _job(skills_tags=[])
    candidate = _candidate(experience_years=3)  # default from _candidate()
    result = score_candidate(job, candidate)
    assert result.confidence < 0.5
    # No skill signal at all (job has none to match against) -- score
    # is purely the capped experience bonus: 3 years * 2 pts = 6.0
    assert result.match_score == 6.0


def test_rank_candidates_sorts_descending_by_score():
    job = _job()
    strong = _candidate(skills=["python", "fastapi", "postgres"], experience_years=5)
    weak = _candidate(skills=["python"], experience_years=0)
    ranked = rank_candidates(job, [weak, strong])
    assert ranked[0].user_id == strong.user_id
    assert ranked[1].user_id == weak.user_id


def test_rag_job_similarity_returns_empty_for_no_history():
    job = _job()
    assert find_similar_past_jobs(job, None) == []
    assert find_similar_past_jobs(job, []) == []


def test_rag_job_similarity_ranks_by_skill_overlap():
    job = _job(skills_tags=["python", "fastapi", "postgres"])
    very_similar = _job(skills_tags=["python", "fastapi", "postgres"])
    somewhat_similar = _job(skills_tags=["python", "django"])
    unrelated = _job(skills_tags=["react", "typescript"])

    results = find_similar_past_jobs(job, [unrelated, somewhat_similar, very_similar], top_k=3)
    ordered_ids = [j.job_id for j, _score in results]
    assert ordered_ids[0] == very_similar.job_id
    assert ordered_ids[-1] == unrelated.job_id


def test_rag_job_similarity_respects_top_k():
    job = _job()
    history = [_job(skills_tags=["python"]) for _ in range(10)]
    results = find_similar_past_jobs(job, history, top_k=3)
    assert len(results) == 3