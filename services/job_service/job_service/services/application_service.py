# LOCATION: services/job_service/job_service/services/application_service.py

"""
Application submission + review business logic (Section: STAGE 2 —
APPLICATION, STAGE 4 — SHORTLISTING).

Candidate-facing methods (`submit_application`, `get_my_application`)
are scoped to the calling candidate's own user_id, same discipline as
user_profile_service's ProfileService/ResumeService -- there is no
"submit on behalf of another candidate" path. Recruiter-facing methods
(`list_applicants`, `advance`, `reject`) take org_id from the caller's
verified tenant-scoped token, same as JobPostingService.
"""

from __future__ import annotations

import uuid

from insynchire_events import Topics
from insynchire_events.schemas import ApplicationSubmittedEvent, CandidateAdvancedEvent, CandidateRejectedEvent
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JobApplication
from ..repositories import JobApplicationRepository, JobOpeningRepository


class ApplicationError(Exception):
    """Base class for application failures."""


class JobNotOpenError(ApplicationError):
    def __init__(self):
        super().__init__("This job is not currently accepting applications")


class AlreadyAppliedError(ApplicationError):
    def __init__(self):
        super().__init__("You have already applied to this job")


class ApplicationNotFoundError(ApplicationError):
    def __init__(self):
        super().__init__("Application not found")


class ApplicationNotInThisOrgError(ApplicationError):
    def __init__(self):
        super().__init__("This application does not belong to your organization")


class ApplicationService:
    def __init__(self, *, publish):
        self._publish = publish

    async def submit_application(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        candidate_user_id: uuid.UUID,
        resume_id: uuid.UUID | None,
        cover_note: str | None,
        trace_id: str,
    ) -> JobApplication:
        job_repo = JobOpeningRepository(session)
        job = await job_repo.get_by_id(job_id)
        if job is None or job.status != "OPEN":
            raise JobNotOpenError()

        app_repo = JobApplicationRepository(session)
        existing = await app_repo.get_by_job_and_candidate(job_id, candidate_user_id)
        if existing is not None:
            raise AlreadyAppliedError()

        try:
            application = await app_repo.create(
                tenant_id=tenant_id, job_id=job_id, candidate_user_id=candidate_user_id,
                resume_id=resume_id, cover_note=cover_note,
            )
            await job_repo.increment_application_count(job)
            await session.commit()
        except IntegrityError as exc:
            # Race: two concurrent apply requests for the same
            # candidate+job both passed the get_by_job_and_candidate
            # check before either committed -- the DB's unique
            # constraint (uq_job_applications_job_candidate) is the
            # authoritative second layer that catches this.
            await session.rollback()
            raise AlreadyAppliedError() from exc

        await session.refresh(application)

        await self._publish(
            Topics.APPLICATION_SUBMITTED.value,
            ApplicationSubmittedEvent(
                trace_id=trace_id, tenant_id=tenant_id, application_id=application.application_id,
                job_id=job_id, candidate_user_id=candidate_user_id,
                resume_id=resume_id or uuid.UUID(int=0),
            ),
        )
        return application

    async def get_my_application(
        self, session: AsyncSession, *, job_id: uuid.UUID, candidate_user_id: uuid.UUID
    ) -> JobApplication | None:
        return await JobApplicationRepository(session).get_by_job_and_candidate(job_id, candidate_user_id)

    async def _get_owned_application(
        self, session: AsyncSession, *, application_id: uuid.UUID, org_id: uuid.UUID
    ) -> JobApplication:
        app_repo = JobApplicationRepository(session)
        application = await app_repo.get_by_id(application_id)
        if application is None:
            raise ApplicationNotFoundError()
        job = await JobOpeningRepository(session).get_by_id(application.job_id)
        if job is None or job.org_id != org_id:
            raise ApplicationNotInThisOrgError()
        return application

    async def list_applicants(
        self, session: AsyncSession, *, job_id: uuid.UUID, org_id: uuid.UUID
    ) -> list[JobApplication]:
        job = await JobOpeningRepository(session).get_by_id(job_id)
        if job is None or job.org_id != org_id:
            raise ApplicationNotInThisOrgError()
        return await JobApplicationRepository(session).list_for_job(job_id)

    async def advance(
        self, session: AsyncSession, *, application_id: uuid.UUID, org_id: uuid.UUID,
        advanced_by: uuid.UUID, tenant_id: uuid.UUID, trace_id: str,
    ) -> JobApplication:
        application = await self._get_owned_application(session, application_id=application_id, org_id=org_id)
        application = await JobApplicationRepository(session).set_status(
            application, status="ADVANCED", reviewed_by=advanced_by
        )
        await session.commit()
        await session.refresh(application)

        await self._publish(
            Topics.CANDIDATE_ADVANCED.value,
            CandidateAdvancedEvent(
                trace_id=trace_id, tenant_id=tenant_id, application_id=application_id,
                job_id=application.job_id, candidate_user_id=application.candidate_user_id,
                new_stage="ADVANCED", advanced_by=advanced_by,
            ),
        )
        return application

    async def reject(
        self, session: AsyncSession, *, application_id: uuid.UUID, org_id: uuid.UUID,
        rejected_by: uuid.UUID, tenant_id: uuid.UUID, reason: str | None, trace_id: str,
    ) -> JobApplication:
        application = await self._get_owned_application(session, application_id=application_id, org_id=org_id)
        application = await JobApplicationRepository(session).set_status(
            application, status="REJECTED", reviewed_by=rejected_by
        )
        await session.commit()
        await session.refresh(application)

        await self._publish(
            Topics.CANDIDATE_REJECTED.value,
            CandidateRejectedEvent(
                trace_id=trace_id, tenant_id=tenant_id, application_id=application_id,
                job_id=application.job_id, candidate_user_id=application.candidate_user_id,
                rejected_by=rejected_by, reason=reason,
            ),
        )
        return application