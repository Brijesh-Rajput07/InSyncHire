# LOCATION: services/tenant_service/tenant_service/services/tenant_provisioning_consumer_service.py

"""
Consumes `tenant.created` (published by Migration Service once it
finishes provisioning a tenant DB — Section: Tenant Onboarding Flow,
step 2) and completes step 4: creates the tenant's default
Organization and assigns the tenant's creator as `company_admin` in
`tenant_user_memberships`.

This is the ONLY place a `company_admin` role gets assigned this way —
every other membership comes through the invite-and-accept flow
(invite_service.py / invite_acceptance_service.py), which deliberately
does not allow inviting someone as company_admin (see invite_schemas.py).
"""

from __future__ import annotations

import logging

from insynchire_events.schemas import TenantCreatedEvent

from ..repositories import MembershipRepository, OrganizationRepository
from ..tenant_db import TenantResolver

logger = logging.getLogger("tenant_service.provisioning_consumer")


class TenantProvisioningConsumerService:
    def __init__(self, *, tenant_resolver: TenantResolver, global_tenant_repository):
        self._tenant_resolver = tenant_resolver
        self._global_tenant_repository = global_tenant_repository

    async def handle_tenant_created(self, event: TenantCreatedEvent) -> None:
        # Need the tenant's created_by_user_id, which isn't on
        # TenantCreatedEvent itself (Section: only tenant_id, subdomain,
        # company_domain, plan) -- look the tenant row up directly.
        tenant = await self._global_tenant_repository.get_by_id(event.tenant_id)

        session, _ = await self._tenant_resolver.get_session_for_tenant_id(event.tenant_id)
        try:
            org = await OrganizationRepository(session).create(
                tenant_id=event.tenant_id, name=tenant.company_name
            )
            await MembershipRepository(session).create(
                user_id=tenant.created_by_user_id,
                tenant_id=event.tenant_id,
                org_id=org.org_id,
                role="company_admin",
                invited_by=None,
            )
            await session.commit()
            logger.info(
                "assigned company_admin: tenant_id=%s user_id=%s org_id=%s",
                event.tenant_id, tenant.created_by_user_id, org.org_id,
            )
        finally:
            await session.close()
