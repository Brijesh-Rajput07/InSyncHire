# LOCATION: services/interview_service/interview_service/broadcaster.py

"""
In-process message broadcaster for the interview WebSocket gateway.

*** INTERIM IMPLEMENTATION -- READ BEFORE MODIFYING ***
Tech Stack section: "Redis Pub/Sub: WebSocket message broker across
multiple FastAPI instances." This module only broadcasts within the
CURRENT PROCESS's connection registry -- correct for a single Interview
Service instance (matches this milestone's dev/test setup and any
single-pod deployment), but NOT correct once Interview Service is
horizontally scaled to multiple processes/pods, where a connection on
instance A would never see a message from a client connected to
instance B.

Swapping in a Redis pub/sub-backed broadcaster is a drop-in
replacement: publish every outgoing message to an
`interview:{session_id}` channel, have every instance subscribe on
startup and fan out to its own LOCAL `SessionConnectionRegistry`. The
`publish()` signature below is deliberately already shaped for that —
callers (`ws_gateway.py`) never touch the registry directly, only this
class — so making that swap later doesn't require touching any call
site. Flagged explicitly rather than silently deferred, same pattern as
`job_service.services.public_board_service`'s interim cross-tenant scan
and `agent_service.tools.rag_job_similarity_tool`'s interim
Jaccard-similarity stand-in.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from .connection_manager import Connection, SessionConnectionRegistry

logger = logging.getLogger("interview_service.broadcaster")


class InProcessBroadcaster:
    def __init__(self, registry: SessionConnectionRegistry):
        self._registry = registry

    async def publish(
        self,
        session_id: uuid.UUID,
        message: dict[str, Any],
        *,
        only_roles: set[str] | None = None,
        exclude_roles: set[str] = frozenset(),
        exclude_connection: Connection | None = None,
    ) -> None:
        """Sends `message` (JSON-serializable) to every connection on
        this session, subject to `only_roles`/`exclude_roles` filtering
        (Section: "Observer: server never sends Co-Pilot or Integrity
        events to observer connections, not just hidden in UI" --
        `ws_gateway.py` uses `only_roles={'interviewer'}` for exactly
        that class of event). Send failures for one stale connection
        never abort delivery to the rest -- cleanup happens when that
        connection's own receive loop raises `WebSocketDisconnect`."""
        for connection in self._registry.list_for_session(session_id):
            if connection is exclude_connection:
                continue
            if connection.role_in_session in exclude_roles:
                continue
            if only_roles is not None and connection.role_in_session not in only_roles:
                continue
            try:
                await connection.websocket.send_json(message)
            except Exception as exc:  # noqa: BLE001 - best-effort fan-out
                logger.warning(
                    "failed to deliver message to session_id=%s user_id=%s: %s",
                    session_id, connection.user_id, exc,
                )