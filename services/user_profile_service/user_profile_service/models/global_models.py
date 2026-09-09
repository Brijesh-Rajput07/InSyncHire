# LOCATION: services/user_profile_service/user_profile_service/models/global_models.py

"""
Read-only mirror of `global_users` (insynchire_global) -- ONLY the
columns this service actually needs (account_type), same minimal-mirror
pattern used by tenant_service/models/global_models.py.

Why this service needs it at all: candidate tokens are always issued
with role=None (Section 1 / auth_service/services/login_service.py --
"tenant_id/org_id/role left unset" applies just as much to candidates,
who never select a tenant at all). There is no "candidate" role value
ever present on a token. So /profile/* routes (which PERMISSION_MATRIX
scopes to `["candidate"]`) cannot be enforced by role alone -- this
service's `auth_dependency.get_current_candidate` additionally checks
`account_type == "candidate"` here before allowing the request through.
This service never writes global_users -- that's entirely Auth
Service's job.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import GUID

from .base import GlobalBase


class GlobalUser(GlobalBase):
    __tablename__ = "global_users"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)