# LOCATION: services/tenant_service/tenant_service/schemas/tenant_select_schemas.py

"""
Pydantic schemas for "select active tenant" — a company_user logs in
globally (Auth Service, M2) with tenant_id/org_id/role left unset on
their token; this endpoint looks up their membership in a specific
tenant (identified by subdomain) and issues a NEW token pair WITH
tenant_id/org_id/role populated.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class SelectTenantRequest(BaseModel):
    subdomain: str


class SelectTenantResponse(BaseModel):
    tenant_id: uuid.UUID
    org_id: uuid.UUID
    role: str
    message: str = "Tenant context selected"
