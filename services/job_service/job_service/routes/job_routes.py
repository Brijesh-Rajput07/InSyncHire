# LOCATION: services/job_service/job_service/routes/job_routes.py

"""
`/jobs*` routes -- recruiter/company_admin job posting CRUD + applicant
list (Section: STAGE 1 — JOB POSTING, STAGE 4 — SHORTLISTING intake).
Every route opens a session scoped to the CALLER'S OWN tenant_id (from
their verified, tenant-selected token) via TenantResolver, then further
scopes every query to their org_id (Section 10b: two independent
isolation layers -- RLS at the DB session level, explicit org_id
filtering at the repository level).
"""

from __future__ import annotations

import uuid

from auth_tokens import TokenPayload
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth_dependency import enforce_permission_matrix
from ..dependencies import get_application_service, get_job_posting_service, get_publish, get_tenant_resolver
from ..schemas import ApplicationResponse, CreateJobRequest, JobResponse, UpdateJobRequest
from ..services import (
    ApplicationNotInThisOrgError,
    ApplicationService,
    JobNotFoundError,
    JobNotInThisOrgError,
    JobPostingError,
    JobPostingService,
)
from ..tenant_db import TenantResolver

router = APIRouter(prefix="/jobs")


def _trace_id(request: Request) -> str:
    return request.headers.get("x-trace-id", str(uuid.uuid4()))


def _job_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, (JobNotFoundError, ApplicationNotInThisOrgError)):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, JobNotInThisOrgError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: CreateJobRequest,
    request: Request,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: JobPostingService = Depends(get_job_posting_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        job = await service.create_job(
            session=session, tenant_id=identity.tenant_id, org_id=identity.org_id,
            posted_by=identity.user_id, create_data=body.model_dump(), trace_id=_trace_id(request),
        )
        return JobResponse.model_validate(job)
    finally:
        await session.close()


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: JobPostingService = Depends(get_job_posting_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        jobs = await service.list_jobs(session, org_id=identity.org_id)
        return [JobResponse.model_validate(j) for j in jobs]
    finally:
        await session.close()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: JobPostingService = Depends(get_job_posting_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        try:
            job = await service.get_job(session, job_id=job_id, org_id=identity.org_id)
        except JobPostingError as exc:
            raise _job_error_to_http(exc) from exc
        return JobResponse.model_validate(job)
    finally:
        await session.close()


@router.put("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: uuid.UUID,
    body: UpdateJobRequest,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: JobPostingService = Depends(get_job_posting_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        try:
            job = await service.update_job(
                session, job_id=job_id, org_id=identity.org_id, update_data=body.model_dump(exclude_unset=True)
            )
        except JobPostingError as exc:
            raise _job_error_to_http(exc) from exc
        return JobResponse.model_validate(job)
    finally:
        await session.close()


@router.delete("/{job_id}", response_model=JobResponse)
async def close_job(
    job_id: uuid.UUID,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: JobPostingService = Depends(get_job_posting_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    """Closes the job (status=CLOSED) -- never a hard delete (see
    JobPostingService.close_job's docstring)."""
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        try:
            job = await service.close_job(session, job_id=job_id, org_id=identity.org_id)
        except JobPostingError as exc:
            raise _job_error_to_http(exc) from exc
        return JobResponse.model_validate(job)
    finally:
        await session.close()


@router.get("/{job_id}/applicants", response_model=list[ApplicationResponse])
async def list_applicants(
    job_id: uuid.UUID,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: ApplicationService = Depends(get_application_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    """Recruiter view of every applicant for a job (Section: STAGE 3 —
    AI RANKING -- "recruiter sees ranking WITH evidence... AI output is
    advisory. Recruiter can see all applicants regardless of rank").
    `ai_rank`/`ai_rank_evidence` are null until the AI Ranking Agent
    (M6) exists and populates them -- this endpoint already returns the
    field so M6 is purely additive, no response-shape change needed."""
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        try:
            applications = await service.list_applicants(session, job_id=job_id, org_id=identity.org_id)
        except ApplicationNotInThisOrgError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return [ApplicationResponse.model_validate(a) for a in applications]
    finally:
        await session.close()