# LOCATION: services/tenant_service/tenant_service/routes/selection_routes.py

"""'Select active tenant' route -- see tenant_selection_service.py."""

from __future__ import annotations

from auth_tokens import TokenPayload, session_fingerprint
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..auth_dependency import enforce_permission_matrix
from ..config import get_config
from ..cookies import set_auth_cookies
from ..dependencies import get_tenant_selection_service
from ..schemas import SelectTenantRequest, SelectTenantResponse
from ..services import MembershipInactiveError, NoMembershipError, TenantSelectionService
from ..tenant_db import TenantNotActiveError, TenantNotFoundError

router = APIRouter(prefix="/tenant")


def _fingerprint(request: Request) -> str:
    return session_fingerprint(
        ip_address=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent", "unknown"),
    )


@router.post("/select", response_model=SelectTenantResponse, status_code=status.HTTP_200_OK)
async def select_tenant(
    body: SelectTenantRequest,
    request: Request,
    response: Response,
    identity: TokenPayload = Depends(enforce_permission_matrix()),
    service: TenantSelectionService = Depends(get_tenant_selection_service),
):
    try:
        result = await service.select(
            user_id=identity.user_id, subdomain=body.subdomain, fingerprint=_fingerprint(request)
        )
    except TenantNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such company") from exc
    except TenantNotActiveError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except NoMembershipError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except MembershipInactiveError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    set_auth_cookies(response, result.tokens, get_config())
    return SelectTenantResponse(tenant_id=result.tenant_id, org_id=result.org_id, role=result.role)
