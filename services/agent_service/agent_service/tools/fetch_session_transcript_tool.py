# LOCATION: services/agent_service/agent_service/tools/fetch_session_transcript_tool.py

"""
`fetch_session_transcript_tool` (Section: GRAPH 1 -- `report_synthesis_node`
-- "fetch_session_transcript_tool(session_id) → chat + any STT transcript").

*** GAP FLAGGED, NOT FAKED ***
M9's WebSocket gateway (`interview_service/ws_gateway.py`) RELAYS chat
messages between connections but does not PERSIST them -- there is no
`chat_messages` table anywhere in the tenant Alembic chain
(`0001_initial` through `0006_code_snapshots`). Speech-to-text is
entirely out of scope of everything built so far. This means there is
currently no real data source this tool could honestly fetch from.

Per this project's own "don't invent data to fake it" convention (see
Notification Service's `agent.integrity_flagged` handler and
`user_profile_service`'s `application.submitted`/`scorecard.generated`
in-app-notification gap, both of which log loudly and do nothing rather
than guess), this tool ALWAYS returns `available=False` with an empty
transcript and a `gap_reason` explaining why, rather than fabricating
placeholder transcript text that `report_synthesis_node` might
otherwise treat as real evidence.

**Recommended fix, not applied here without confirmation (per the
continuation prompt's own suggestion):** a small, explicitly-scoped
FIX-M9 adding a `chat_messages` table (tenant DB, RLS, same pattern as
`code_snapshots`) + a `ChatMessageRepository`, with
`ws_gateway.py`'s `_handle_chat` persisting each message the same way
`_handle_code_update` already persists snapshots. Until that lands,
`report_synthesis_node` must treat `overall_summary`/`recommendation_rationale`
as based on code history + integrity signals + question history only —
never on a transcript that doesn't exist.
"""

from __future__ import annotations

from ..schemas.interview_io_schemas import TranscriptFetchResult

NO_CHAT_PERSISTENCE_GAP_REASON = (
    "No chat_messages table exists yet -- interview_service's WebSocket gateway (M9) "
    "relays chat between connections but does not persist it. See FIX-M9 note in "
    "fetch_session_transcript_tool.py's module docstring."
)


def fetch_session_transcript(*, session_id) -> TranscriptFetchResult:  # noqa: ANN001 - session_id typed loosely (str|UUID) by callers
    """Always returns `available=False` until chat persistence exists
    (see module docstring) -- never fabricates transcript content."""
    return TranscriptFetchResult(
        available=False,
        transcript_text="",
        message_count=0,
        gap_reason=NO_CHAT_PERSISTENCE_GAP_REASON,
    )