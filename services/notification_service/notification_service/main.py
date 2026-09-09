# LOCATION: services/notification_service/notification_service/main.py

"""
Notification Service entrypoint -- headless only, no HTTP routes
(Section 3, Section 6: "notification_service/ ← headless Kafka
consumer, no routes").

Subscribes to every topic named in Task N, each routed to the matching
`NotificationDispatchService.handle_*` method. One `subscribe()` call
per topic (same fan-out pattern `user_profile_service`/`tenant_service`
already use for their own consumers) run concurrently via
`asyncio.gather`.

Run locally with:
  python -m notification_service.main serve
"""

from __future__ import annotations

import asyncio
import logging

from insynchire_events import Topics, subscribe
from insynchire_events.schemas import (
    AgentIntegrityFlaggedEvent,
    ApplicationSubmittedEvent,
    CandidateAdvancedEvent,
    CandidateRejectedEvent,
    InterviewScheduledEvent,
    ScorecardGeneratedEvent,
    UserInvitedEvent,
)

from .config import get_config
from .dependencies import get_notification_dispatch_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("notification_service.main")


async def serve() -> None:
    """Runs forever, consuming all seven notification-relevant topics
    concurrently. A single `NotificationDispatchService` instance is
    shared across all of them -- it holds no per-event mutable state."""
    dispatch_service = get_notification_dispatch_service()
    group_id = get_config().kafka_consumer_group

    async def handle_user_invited(event: UserInvitedEvent) -> None:
        await dispatch_service.handle_user_invited(event)

    async def handle_application_submitted(event: ApplicationSubmittedEvent) -> None:
        await dispatch_service.handle_application_submitted(event)

    async def handle_candidate_advanced(event: CandidateAdvancedEvent) -> None:
        await dispatch_service.handle_candidate_advanced(event)

    async def handle_candidate_rejected(event: CandidateRejectedEvent) -> None:
        await dispatch_service.handle_candidate_rejected(event)

    async def handle_interview_scheduled(event: InterviewScheduledEvent) -> None:
        await dispatch_service.handle_interview_scheduled(event)

    async def handle_scorecard_generated(event: ScorecardGeneratedEvent) -> None:
        await dispatch_service.handle_scorecard_generated(event)

    async def handle_agent_integrity_flagged(event: AgentIntegrityFlaggedEvent) -> None:
        await dispatch_service.handle_agent_integrity_flagged(event)

    logger.info("Notification Service starting -- subscribing to 7 topics")
    await asyncio.gather(
        subscribe(Topics.USER_INVITED.value, handle_user_invited, group_id=f"{group_id}_user_invited"),
        subscribe(
            Topics.APPLICATION_SUBMITTED.value, handle_application_submitted,
            group_id=f"{group_id}_application_submitted",
        ),
        subscribe(
            Topics.CANDIDATE_ADVANCED.value, handle_candidate_advanced, group_id=f"{group_id}_candidate_advanced"
        ),
        subscribe(
            Topics.CANDIDATE_REJECTED.value, handle_candidate_rejected, group_id=f"{group_id}_candidate_rejected"
        ),
        subscribe(
            Topics.INTERVIEW_SCHEDULED.value, handle_interview_scheduled,
            group_id=f"{group_id}_interview_scheduled",
        ),
        subscribe(
            Topics.SCORECARD_GENERATED.value, handle_scorecard_generated,
            group_id=f"{group_id}_scorecard_generated",
        ),
        subscribe(
            Topics.AGENT_INTEGRITY_FLAGGED.value, handle_agent_integrity_flagged,
            group_id=f"{group_id}_agent_integrity_flagged",
        ),
    )


def main() -> None:
    import sys

    if len(sys.argv) < 2 or sys.argv[1] != "serve":
        print("Usage: python -m notification_service.main serve")
        sys.exit(1)
    asyncio.run(serve())


if __name__ == "__main__":
    main()