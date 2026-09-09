# LOCATION: services/agent_service/agent_service/services/ranking_agent_service.py

"""
`RankingAgentService` -- the entry point Job Service (or, for now, a
test/caller) uses to run the AI Ranking Agent graph (Task J). Owns:

  1. Compiling the graph once (`build_ranking_graph`) and reusing it
     across calls -- each individual ranking run gets its own
     `thread_id` so LangGraph's checkpointer keeps their state isolated.
  2. `start_ranking()` -- runs the graph up to (and pausing before)
     `human_approval_node`, per Section: GRAPH 2's interrupt.
  3. `resume_after_human_decision()` -- the recruiter's approve/reject
     call resumes the graph; on approval (and only if the run wasn't
     guardrail-blocked), publishes `agent.ranking_completed` to Kafka
     (Section Kafka Topics: "agent.ranking_completed → Reporting
     Service, Job Service").

This milestone does not yet persist `RankingResult` to
`job_applications.ai_rank`/`ai_rank_evidence` in a tenant DB -- that
write belongs to Job Service (which owns `job_applications`), triggered
by consuming `agent.ranking_completed`, following the exact same
no-cross-service-DB-writes precedent FIX-M2 established and M5's
`user_applications_index` consumer already follows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..graphs.ranking_graph import RankingGraphState, build_ranking_graph
from ..guardrails import GuardrailService
from ..schemas.agent_io_schemas import RankingResult
from ..schemas.ranking_schemas import CandidateProfileInput, JobOpeningInput

PublishFn = Callable[[str, Any], Awaitable[None]]

AGENT_RANKING_COMPLETED_TOPIC = "agent.ranking_completed"


class RankingRunNotFoundError(Exception):
    def __init__(self, thread_id: str):
        super().__init__(f"No ranking run found for thread_id={thread_id!r} (already resumed, or never started?)")


@dataclass
class RankingRunResult:
    thread_id: str
    blocked: bool
    block_reason: str | None
    awaiting_human_approval: bool
    ranking_result: RankingResult | None
    published: bool = False
    """True once `agent.ranking_completed` was actually published --
    only ever True after a successful `resume_after_human_decision(approved=True)`."""


class RankingAgentService:
    def __init__(
        self,
        *,
        guardrail_service: GuardrailService,
        narrative_llm_call: Callable[[str], Awaitable[str]],
        publish: PublishFn | None = None,
    ):
        self._guardrail_service = guardrail_service
        self._publish = publish
        self._graph = build_ranking_graph(guardrail_service=guardrail_service, narrative_llm_call=narrative_llm_call)

    def _config_for(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _to_run_result(thread_id: str, state: dict, *, published: bool = False) -> RankingRunResult:
        ranking_result_dict = state.get("ranking_result")
        return RankingRunResult(
            thread_id=thread_id,
            blocked=bool(state.get("blocked")),
            block_reason=state.get("block_reason"),
            awaiting_human_approval=not state.get("blocked") and ranking_result_dict is not None,
            ranking_result=RankingResult.model_validate(ranking_result_dict) if ranking_result_dict else None,
            published=published,
        )

    async def start_ranking(
        self,
        *,
        job_opening: JobOpeningInput,
        candidate_profiles: list[CandidateProfileInput],
        historical_jobs: list[JobOpeningInput] | None = None,
        tenant_id: uuid.UUID | None = None,
        trace_id: str = "unset",
        thread_id: str | None = None,
    ) -> RankingRunResult:
        """Runs the graph through bias_scan_node, then pauses (LangGraph
        interrupt_before) right before human_approval_node. If any node
        along the way sets `blocked`, the graph reaches END early via
        the conditional edges and there's nothing to approve --
        `awaiting_human_approval` will be False in that case."""
        thread_id = thread_id or f"ranking:{job_opening.job_id}:{uuid.uuid4().hex[:8]}"

        initial_state: RankingGraphState = {
            "trace_id": trace_id,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "job_opening": job_opening.model_dump(mode="json"),
            "candidate_profiles": [c.model_dump(mode="json") for c in candidate_profiles],
            "historical_jobs": [j.model_dump(mode="json") for j in (historical_jobs or [])],
            "sanitized_bios": {},
            "raw_ranking_output": None,
            "ranking_result": None,
            "human_approved": False,
            "blocked": False,
            "block_reason": None,
        }

        result_state = await self._graph.ainvoke(initial_state, config=self._config_for(thread_id))
        return self._to_run_result(thread_id, result_state)

    async def resume_after_human_decision(
        self, *, thread_id: str, approved: bool, tenant_id: uuid.UUID | None = None, trace_id: str = "unset",
    ) -> RankingRunResult:
        """Section: 'recruiter sees ranking WITH evidence. Makes final
        call.' Approving publishes `agent.ranking_completed`; rejecting
        does not -- the recruiter can still see all applicants
        regardless of rank (Section: STAGE 3), they've just indicated
        the AI ranking itself shouldn't be treated as final for this
        job (a future milestone could re-trigger `start_ranking` here;
        out of scope for M6)."""
        config = self._config_for(thread_id)

        current_state = await self._graph.aget_state(config)
        if not current_state.values:
            raise RankingRunNotFoundError(thread_id)

        await self._graph.aupdate_state(config, {"human_approved": approved})
        result_state = await self._graph.ainvoke(None, config=config)

        published = False
        if approved and not result_state.get("blocked") and result_state.get("ranking_result") is not None:
            if self._publish is not None:
                await self._publish(
                    AGENT_RANKING_COMPLETED_TOPIC,
                    self._build_ranking_completed_event(result_state, tenant_id=tenant_id, trace_id=trace_id),
                )
            published = True

        return self._to_run_result(thread_id, result_state, published=published)

    @staticmethod
    def _build_ranking_completed_event(state: dict, *, tenant_id: uuid.UUID | None, trace_id: str):
        """Builds the SHARED `insynchire_events.schemas.AgentRankingCompletedEvent`
        (the registered schema for `agent.ranking_completed`). Imported
        lazily -- same rationale as `GuardrailService._to_guardrail_event`:
        constructing a `RankingAgentService` without a `publish` callable
        should never require `insynchire-events` to be installed."""
        from insynchire_events.schemas import AgentRankingCompletedEvent

        job_id = uuid.UUID(state["job_opening"]["job_id"])
        ranked_count = len(state["ranking_result"]["ranked_candidates"])
        return AgentRankingCompletedEvent(
            trace_id=trace_id,
            tenant_id=tenant_id or (uuid.UUID(state["tenant_id"]) if state["tenant_id"] else None),
            job_id=job_id,
            ranked_candidate_count=ranked_count,
        )