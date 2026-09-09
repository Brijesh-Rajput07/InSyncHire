# LOCATION: services/job_service/job_service/services/public_board_service.py

"""
Public candidate job board (Section: STAGE 1 — "Public listing on
candidate job board (via reporting_db aggregate — candidates NEVER
query tenant DB directly)").

*** INTERIM IMPLEMENTATION -- READ BEFORE MODIFYING ***
The project plan specifies this reads a pre-built aggregate from
`reporting_db`, populated by the Reporting Service consuming Kafka
events. Reporting Service is Milestone M12 and does not exist yet in
this build order (M5 comes long before it). Rather than block Job
Service on a service four milestones away, this implementation scans
every ACTIVE tenant's OWN database directly (via TenantResolver,
bounded by `public_board_max_tenants_scanned`) and builds the aggregate
on the fly, on every request.

This satisfies the SPIRIT of the rule at the API boundary a candidate
actually touches -- they call Job Service's `/public/jobs`, never a
tenant DB connection string, exactly as intended -- but violates the
letter of it internally (this service, not Reporting Service, is doing
the cross-tenant read) and does not scale (O(N) tenant DB connections
per request, no caching). When Reporting Service (M12) is built, this
method's body should be replaced with a single read against
`reporting_db`'s aggregate table, and TenantResolver.list_active_tenants
/ this service's dependency on TenantResolver for the public board can
be removed entirely (recruiter/company_admin routes will still need
TenantResolver for their own tenant-scoped requests).
"""

from __future__ import annotations

from ..repositories import JobOpeningRepository
from ..tenant_db import TenantNotActiveError, TenantResolver


class PublicBoardService:
    def __init__(self, *, tenant_resolver: TenantResolver, max_tenants_scanned: int):
        self._tenant_resolver = tenant_resolver
        self._max_tenants_scanned = max_tenants_scanned

    async def list_open_jobs(self) -> list[dict]:
        """Returns plain dicts (not ORM objects) shaped like
        `PublicJobResponse`, since each job comes from a DIFFERENT
        tenant DB session that gets closed before this method returns --
        returning ORM instances would risk detached-instance errors."""
        tenants = await self._tenant_resolver.list_active_tenants(self._max_tenants_scanned)

        aggregated: list[dict] = []
        for tenant in tenants:
            try:
                session, _ = await self._tenant_resolver.get_session_for_tenant_id(tenant.tenant_id)
            except TenantNotActiveError:
                continue
            try:
                jobs = await JobOpeningRepository(session).list_open()
                for job in jobs:
                    aggregated.append(
                        {
                            "job_id": job.job_id,
                            "tenant_id": tenant.tenant_id,
                            "tenant_subdomain": tenant.subdomain,
                            "company_name": tenant.company_name,
                            "title": job.title,
                            "description": job.description,
                            "skills_tags": job.skills_tags,
                            "experience_level": job.experience_level,
                            "location": job.location,
                            "salary_min": job.salary_min,
                            "salary_max": job.salary_max,
                            "application_count": job.application_count,
                            "created_at": job.created_at,
                        }
                    )
            finally:
                await session.close()

        aggregated.sort(key=lambda j: j["created_at"], reverse=True)
        return aggregated