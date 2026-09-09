# LOCATION: services/interview_service/interview_service/__init__.py

"""Interview Service (M8) -- scheduling, room-token issuance, invite-
triggering (publishes interview.scheduled -- already consumed by
Notification Service and User Profile Service's in-app notification
consumer, both built in M7), and join records for interview sessions.

Does NOT include the live WebSocket room, Yjs CRDT sync, video/voice,
or the LangGraph interview pipeline graph (Graph 1) -- those are M9/M10.
See Section 3 / Task L (scheduling half) of the project plan.
"""