# LOCATION: services/auth_service/auth_service/routes/signup_routes.py

"""
Signup routes (Tasks C + D). Thin per Section 6 -- all logic lives in
the services layer; routes just validate the request shape (via
Pydantic), call a service, translate exceptions to HTTP status codes,
and set cookies.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..cookies import set_auth_cookies
from ..config import get_config
from ..dependencies import (
    get_candidate_signup_service,
    get_company_signup_service,
    get_global_session,
)
from ..schemas import (
    CandidateSignupCompleteResponse,
    CandidateSignupInitiatedResponse,
    CandidateSignupRequest,
    CandidateSignupVerifyOTPRequest,
    CompanySignupCompleteResponse,
    CompanySignupInitiatedResponse,
    CompanySignupRequest,
    CompanySignupVerifyOTPRequest,
)
from ..services import (
    CandidatePendingSignupNotFoundError,
    CompanyPendingSignupNotFoundError,
    DomainHasNoMailServerError,
    DomainValidationError,
    OTPIncorrectError,
    OTPLockedError,
    OTPNotFoundOrExpiredError,
    PublicEmailDomainError,
    session_fingerprint,
)
from ..services.candidate_signup_service import CandidateSignupService
from ..services.company_signup_service import CompanySignupService

router = APIRouter()


def _trace_id(request: Request) -> str:
    return request.headers.get("x-trace-id", str(uuid.uuid4()))


def _fingerprint(request: Request) -> str:
    return session_fingerprint(
        ip_address=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent", "unknown"),
    )


def _otp_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, OTPLockedError):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
    if isinstance(exc, OTPNotFoundOrExpiredError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, OTPIncorrectError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --- Company signup ---------------------------------------------------

@router.post(
    "/signup/company", response_model=CompanySignupInitiatedResponse, status_code=status.HTTP_200_OK
)
async def initiate_company_signup(
    body: CompanySignupRequest,
    service: CompanySignupService = Depends(get_company_signup_service),
):
    try:
        result = await service.initiate(
            company_name=body.company_name,
            subdomain=body.subdomain,
            company_email=body.company_email,
            full_name=body.full_name,
            password=body.password,
        )
    except PublicEmailDomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DomainHasNoMailServerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DomainValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return CompanySignupInitiatedResponse(
        company_email=result.company_email, otp_expires_in_seconds=result.otp_expires_in_seconds
    )


@router.post(
    "/signup/company/verify-otp",
    response_model=CompanySignupCompleteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def verify_company_signup_otp(
    body: CompanySignupVerifyOTPRequest,
    request: Request,
    service: CompanySignupService = Depends(get_company_signup_service),
    session: AsyncSession = Depends(get_global_session),
):
    try:
        result = await service.complete(
            session=session,
            company_email=body.company_email,
            otp_code=body.otp_code,
            trace_id=_trace_id(request),
        )
    except CompanyPendingSignupNotFoundError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except (OTPLockedError, OTPNotFoundOrExpiredError, OTPIncorrectError) as exc:
        raise _otp_error_to_http(exc) from exc

    return CompanySignupCompleteResponse(
        tenant_id=result.tenant_id, subdomain=result.subdomain, status=result.status
    )


# --- Candidate signup --------------------------------------------------

@router.post(
    "/signup/candidate", response_model=CandidateSignupInitiatedResponse, status_code=status.HTTP_200_OK
)
async def initiate_candidate_signup(
    body: CandidateSignupRequest,
    service: CandidateSignupService = Depends(get_candidate_signup_service),
):
    result = await service.initiate(email=body.email, full_name=body.full_name, password=body.password)
    return CandidateSignupInitiatedResponse(
        email=result.email, otp_expires_in_seconds=result.otp_expires_in_seconds
    )


@router.post(
    "/signup/candidate/verify-otp",
    response_model=CandidateSignupCompleteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def verify_candidate_signup_otp(
    body: CandidateSignupVerifyOTPRequest,
    request: Request,
    response: Response,
    service: CandidateSignupService = Depends(get_candidate_signup_service),
    global_session: AsyncSession = Depends(get_global_session),
):
    try:
        result = await service.complete(
            global_session=global_session,
            email=body.email,
            otp_code=body.otp_code,
            fingerprint=_fingerprint(request),
            trace_id=_trace_id(request),
        )
    except CandidatePendingSignupNotFoundError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except (OTPLockedError, OTPNotFoundOrExpiredError, OTPIncorrectError) as exc:
        raise _otp_error_to_http(exc) from exc

    set_auth_cookies(response, result.tokens, get_config())
    return CandidateSignupCompleteResponse(user_id=result.user_id, email=result.email)
