# LOCATION: services/agent_service/agent_service/tools/fetch_code_snapshots_tool.py

"""
`fetch_code_snapshots_tool` (Section: GRAPH 1 -- `report_synthesis_node`
-- "fetch_code_snapshots_tool(session_id) → retrieves full code history
from DB").

Unlike `sandbox_execution_tool` (mocked, flagged) and
`rag_question_retrieval_tool` (interim in-memory stand-in), the
UNDERLYING DATA this tool needs IS real: M9 built `code_snapshots` +
`CodeSnapshotRepository` in `interview_service`, on `interview_service`'s
OWN tenant-DB connection (Section 2/6: repository pattern -- Agent
Service does not have, and should not grow, its own direct connection
to `tenant_<id>_db` just to read a table `interview_service` already
owns and exposes a repository for; that would duplicate the
`TenantResolver` wiring `interview_service`/`job_service`/`tenant_service`
each independently maintain for their OWN tables).

So this tool is a thin, DB-agnostic FORMATTER: it takes already-fetched
snapshot rows (as plain dicts shaped like `CodeSnapshotRepository.list_for_session`'s
output) and turns them into the ordered playback list
`report_synthesis_node` needs. The actual fetch — calling
`interview_service`'s `CodeSnapshotRepository.list_for_session` against
that service's own tenant DB session — happens in whatever caller wires
Graph 1 into a live session (M10's WebSocket-trigger integration,
Slice 2, not built in this slice). This keeps the repository pattern
intact: Agent Service never queries a table it doesn't own directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class CodeSnapshotRecord:
    """Mirrors the columns `interview_service.models.CodeSnapshot`
    already defines (Section 5) -- the shape a caller should pass in
    after fetching real rows via `CodeSnapshotRepository.list_for_session`."""

    snapshot_index: int
    content: str
    language: str | None
    diff_from_prev: str | None
    captured_at: datetime


def build_code_history_summary(snapshots: list[CodeSnapshotRecord]) -> str:
    """Formats an ordered list of real snapshot records into the
    compact history string `report_synthesis_node`'s prompt-building
    step embeds inside `<candidate_data>` (Layer 1, Rule 1.4 --
    candidate-authored code is always untrusted, even in its final
    persisted form). Returns an empty string for a session with no
    snapshots (e.g. a purely verbal/whiteboard interview)."""
    if not snapshots:
        return ""

    lines: list[str] = []
    for snap in snapshots:
        lines.append(
            f"--- snapshot {snap.snapshot_index} ({snap.language or 'unknown'}, "
            f"captured_at={snap.captured_at.isoformat()}) ---"
        )
        lines.append(snap.content)
    return "\n".join(lines)