# LOCATION: services/interview_service/interview_service/routes/interview_routes.py

"""
`/interviews*` routes (M8, Section: STAGE 5 -- INTERVIEW SCHEDULING,
STAGE 6's join step). Thin per Section 6 -- all logic lives in the
services layer; routes just validate the request shape, resolve the
right tenant DB session, call a service, translate exceptions to HTTP
status codes.
"""

from __future__ import annotations

import uuid

from auth_tokens import TokenPayload
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth_dependency import InterviewAccessIdentity, enforce_permission_matrix, resolve_join_identity
from ..dependencies import get_join_service, get_scheduling_service, get_tenant_resolver
from ..schemas import InterviewSessionResponse, JoinInterviewResponse, ScheduleInterviewRequest
from ..services import (
    InterviewAccessDeniedError,
    InterviewNotFoundError,
    JoinInterviewNotFoundError,
    JoinService,
    NotAParticipantError,
    SchedulingService,
)
from ..tenant_db import TenantNotActiveError, TenantNotFoundError, TenantResolver

router = APIRouter(prefix="/interviews")


def _trace_id(request: Request) -> str:
    return request.headers.get("x-trace-id", str(uuid.uuid4()))


@router.post("/schedule", response_model=InterviewSessionResponse, status_code=status.HTTP_201_CREATED)
async def schedule_interview(
    body: ScheduleInterviewRequest,
    request: Request,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: SchedulingService = Depends(get_scheduling_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        interview = await service.schedule_interview(
            session=session,
            tenant_id=identity.tenant_id,
            scheduled_by=identity.user_id,
            job_id=body.job_id,
            application_id=body.application_id,
            candidate_user_id=body.candidate_user_id,
            interviewer_ids=body.interviewer_ids,
            observer_ids=body.observer_ids,
            scheduled_at=body.scheduled_at,
            trace_id=_trace_id(request),
        )
        return InterviewSessionResponse.model_validate(interview)
    finally:
        await session.close()


@router.get("/{session_id}", response_model=InterviewSessionResponse)
async def get_interview(
    session_id: uuid.UUID,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: SchedulingService = Depends(get_scheduling_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        try:
            interview = await service.get_session_for_staff(
                session,
                session_id=session_id,
                tenant_id=identity.tenant_id,
                requester_user_id=identity.user_id,
                requester_role=identity.role,
            )
        except InterviewNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except InterviewAccessDeniedError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
        return InterviewSessionResponse.model_validate(interview)
    finally:
        await session.close()


@router.post("/{session_id}/join", response_model=JoinInterviewResponse)
async def join_interview(
    session_id: uuid.UUID,
    access: InterviewAccessIdentity = Depends(resolve_join_identity),
    service: JoinService = Depends(get_join_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    try:
        session, _ = await tenant_resolver.get_session_for_tenant_id(access.tenant_id)
    except (TenantNotFoundError, TenantNotActiveError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such company") from exc

    try:
        try:
            result = await service.join(
                session,
                session_id=session_id,
                tenant_id=access.tenant_id,
                user_id=access.user_id,
                role_in_session=access.role_in_session,
            )
        except JoinInterviewNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except NotAParticipantError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

        return JoinInterviewResponse(
            session_id=result.session.session_id,
            role_in_session=result.participant.role_in_session,
            room_token=result.room_token or "",
            ws_connect_token=result.ws_connect_token,
            joined_at=result.participant.joined_at,
        )
    finally:
        await session.close()