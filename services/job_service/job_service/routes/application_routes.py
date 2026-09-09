# LOCATION: services/job_service/job_service/routes/application_routes.py

"""
Candidate application routes (`/jobs/{id}/apply`, `/jobs/{id}/my-application`)
plus recruiter review routes (`/applications/{id}/advance|reject`).

Candidate routes need an `X-Tenant-Id` header: a candidate's token has
no tenant context at all (Section 1 -- candidates are global, never
tenant-scoped), so there is no way to know which tenant DB a `job_id`
lives in from the token alone. The public job board response
(`PublicJobResponse`) includes `tenant_id` on every listing precisely
so the frontend can pass it back here -- this mirrors the
`X-Tenant-Subdomain` header Tenant Service's invite-acceptance route
already uses to solve the identical "which tenant does this request
concern" problem for an otherwise-tenant-less token.
"""

from __future__ import annotations

import uuid

from auth_tokens import TokenPayload
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth_dependency import enforce_permission_matrix, get_current_candidate
from ..dependencies import get_application_service, get_tenant_resolver
from ..schemas import AdvanceOrRejectRequest, ApplicationResponse, SubmitApplicationRequest
from ..services import (
    AlreadyAppliedError,
    ApplicationError,
    ApplicationNotFoundError,
    ApplicationNotInThisOrgError,
    ApplicationService,
    JobNotOpenError,
)
from ..tenant_db import TenantNotActiveError, TenantNotFoundError, TenantResolver

jobs_router = APIRouter(prefix="/jobs")
applications_router = APIRouter(prefix="/applications")


def _trace_id(request: Request) -> str:
    return request.headers.get("x-trace-id", str(uuid.uuid4()))


def _require_tenant_id_header(request: Request) -> uuid.UUID:
    raw = request.headers.get("x-tenant-id")
    if not raw:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Missing X-Tenant-Id header -- which company's job is this? "
            "(the public job listing response includes tenant_id for exactly this purpose)",
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant-Id header is not a valid UUID") from exc


def _application_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, JobNotOpenError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, AlreadyAppliedError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, (ApplicationNotFoundError, ApplicationNotInThisOrgError)):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@jobs_router.post("/{job_id}/apply", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def apply_to_job(
    job_id: uuid.UUID,
    body: SubmitApplicationRequest,
    request: Request,
    identity: TokenPayload = Depends(get_current_candidate),
    service: ApplicationService = Depends(get_application_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    tenant_id = _require_tenant_id_header(request)
    try:
        session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    except (TenantNotFoundError, TenantNotActiveError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such company") from exc

    try:
        try:
            application = await service.submit_application(
                session=session, tenant_id=tenant_id, job_id=job_id, candidate_user_id=identity.user_id,
                resume_id=body.resume_id, cover_note=body.cover_note, trace_id=_trace_id(request),
            )
        except ApplicationError as exc:
            raise _application_error_to_http(exc) from exc
        return ApplicationResponse.model_validate(application)
    finally:
        await session.close()


@jobs_router.get("/{job_id}/my-application", response_model=ApplicationResponse)
async def get_my_application(
    job_id: uuid.UUID,
    request: Request,
    identity: TokenPayload = Depends(get_current_candidate),
    service: ApplicationService = Depends(get_application_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    tenant_id = _require_tenant_id_header(request)
    try:
        session, _ = await tenant_resolver.get_session_for_tenant_id(tenant_id)
    except (TenantNotFoundError, TenantNotActiveError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such company") from exc

    try:
        application = await service.get_my_application(session, job_id=job_id, candidate_user_id=identity.user_id)
        if application is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "You have not applied to this job")
        return ApplicationResponse.model_validate(application)
    finally:
        await session.close()


@applications_router.post("/{application_id}/advance", response_model=ApplicationResponse)
async def advance_application(
    application_id: uuid.UUID,
    request: Request,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: ApplicationService = Depends(get_application_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        try:
            application = await service.advance(
                session, application_id=application_id, org_id=identity.org_id, advanced_by=identity.user_id,
                tenant_id=identity.tenant_id, trace_id=_trace_id(request),
            )
        except ApplicationError as exc:
            raise _application_error_to_http(exc) from exc
        return ApplicationResponse.model_validate(application)
    finally:
        await session.close()


@applications_router.post("/{application_id}/reject", response_model=ApplicationResponse)
async def reject_application(
    application_id: uuid.UUID,
    body: AdvanceOrRejectRequest,
    request: Request,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: ApplicationService = Depends(get_application_service),
    tenant_resolver: TenantResolver = Depends(get_tenant_resolver),
):
    session, _ = await tenant_resolver.get_session_for_tenant_id(identity.tenant_id)
    try:
        try:
            application = await service.reject(
                session, application_id=application_id, org_id=identity.org_id, rejected_by=identity.user_id,
                tenant_id=identity.tenant_id, reason=body.reason, trace_id=_trace_id(request),
            )
        except ApplicationError as exc:
            raise _application_error_to_http(exc) from exc
        return ApplicationResponse.model_validate(application)
    finally:
        await session.close()