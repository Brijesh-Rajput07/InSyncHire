# LOCATION: services/user_profile_service/user_profile_service/main.py

"""
User Profile Service FastAPI app (M4).

Same shape as Tenant Service (M3): serves HTTP routes (`/profile*`)
AND consumes Kafka topics in the background, in the same process.
M7 adds three more background consumers -- candidate.advanced,
candidate.rejected, interview.scheduled -- writing `user_notifications`
rows (see notification_record_consumer_service.py's module docstring
for the DB-ownership reasoning and the documented scope boundary).

Run locally with:
  uvicorn user_profile_service.main:app --reload --port 8003
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from insynchire_events import Topics, subscribe
from insynchire_events.schemas import (
    ApplicationSubmittedEvent,
    CandidateAdvancedEvent,
    CandidateRejectedEvent,
    InterviewScheduledEvent,
    UserRegisteredEvent,
)

from .config import get_config
from .dependencies import (
    get_application_submitted_consumer_service,
    get_notification_record_consumer_service,
    get_user_registered_consumer_service,
)
from .routes import profile_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("user_profile_service.main")

_user_registered_consumer_task: asyncio.Task | None = None
_application_submitted_consumer_task: asyncio.Task | None = None
_candidate_advanced_notification_task: asyncio.Task | None = None
_candidate_rejected_notification_task: asyncio.Task | None = None
_interview_scheduled_notification_task: asyncio.Task | None = None


async def _run_user_registered_consumer() -> None:
    consumer_service = get_user_registered_consumer_service()

    async def handle(event: UserRegisteredEvent) -> None:
        await consumer_service.handle_user_registered(event)

    await subscribe(Topics.USER_REGISTERED.value, handle, group_id=get_config().kafka_consumer_group)


async def _run_application_submitted_consumer() -> None:
    """M5 addition -- see services/application_submitted_consumer_service.py."""
    consumer_service = get_application_submitted_consumer_service()

    async def handle(event: ApplicationSubmittedEvent) -> None:
        await consumer_service.handle_application_submitted(event)

    await subscribe(
        Topics.APPLICATION_SUBMITTED.value, handle,
        group_id=f"{get_config().kafka_consumer_group}_application_index",
    )


async def _run_candidate_advanced_notification_consumer() -> None:
    """M7 addition -- see services/notification_record_consumer_service.py."""
    consumer_service = get_notification_record_consumer_service()

    async def handle(event: CandidateAdvancedEvent) -> None:
        await consumer_service.handle_candidate_advanced(event)

    await subscribe(
        Topics.CANDIDATE_ADVANCED.value, handle,
        group_id=f"{get_config().kafka_consumer_group}_notification_record",
    )


async def _run_candidate_rejected_notification_consumer() -> None:
    """M7 addition -- see services/notification_record_consumer_service.py."""
    consumer_service = get_notification_record_consumer_service()

    async def handle(event: CandidateRejectedEvent) -> None:
        await consumer_service.handle_candidate_rejected(event)

    await subscribe(
        Topics.CANDIDATE_REJECTED.value, handle,
        group_id=f"{get_config().kafka_consumer_group}_notification_record",
    )


async def _run_interview_scheduled_notification_consumer() -> None:
    """M7 addition -- see services/notification_record_consumer_service.py."""
    consumer_service = get_notification_record_consumer_service()

    async def handle(event: InterviewScheduledEvent) -> None:
        await consumer_service.handle_interview_scheduled(event)

    await subscribe(
        Topics.INTERVIEW_SCHEDULED.value, handle,
        group_id=f"{get_config().kafka_consumer_group}_notification_record",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _user_registered_consumer_task, _application_submitted_consumer_task
    global _candidate_advanced_notification_task, _candidate_rejected_notification_task
    global _interview_scheduled_notification_task

    _user_registered_consumer_task = asyncio.create_task(_run_user_registered_consumer())
    _application_submitted_consumer_task = asyncio.create_task(_run_application_submitted_consumer())
    _candidate_advanced_notification_task = asyncio.create_task(_run_candidate_advanced_notification_consumer())
    _candidate_rejected_notification_task = asyncio.create_task(_run_candidate_rejected_notification_consumer())
    _interview_scheduled_notification_task = asyncio.create_task(_run_interview_scheduled_notification_consumer())
    yield
    for task in (
        _user_registered_consumer_task,
        _application_submitted_consumer_task,
        _candidate_advanced_notification_task,
        _candidate_rejected_notification_task,
        _interview_scheduled_notification_task,
    ):
        if task is not None:
            task.cancel()


app = FastAPI(title="InSyncHire User Profile Service", version="0.1.0", lifespan=lifespan)

app.include_router(profile_router, tags=["profile"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "user_profile_service"}