# LOCATION: services/interview_service/interview_service/connection_manager.py

"""
In-process registry of live WebSocket connections, keyed by
`session_id` (Section: STAGE 6 -- LIVE INTERVIEW ROOM).

`SessionConnectionRegistry` itself has no opinion on authorization or
message routing -- `ws_gateway.py` and `broadcaster.py` build on top of
it. Kept deliberately tiny (a dict of lists) so a future Redis-backed
registry (needed once this service runs as more than one process --
see `broadcaster.py`'s module docstring) can wrap the same shape
without callers changing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import WebSocket


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    user_id: uuid.UUID
    role_in_session: str
    # role_in_session values: company_admin | recruiter | interviewer | observer | candidate


class SessionConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, list[Connection]] = {}

    def add(self, session_id: uuid.UUID, connection: Connection) -> None:
        self._connections.setdefault(session_id, []).append(connection)

    def remove(self, session_id: uuid.UUID, connection: Connection) -> None:
        conns = self._connections.get(session_id)
        if not conns:
            return
        if connection in conns:
            conns.remove(connection)
        if not conns:
            self._connections.pop(session_id, None)

    def list_for_session(self, session_id: uuid.UUID) -> list[Connection]:
        return list(self._connections.get(session_id, []))

    def count_for_session(self, session_id: uuid.UUID) -> int:
        return len(self._connections.get(session_id, []))