# LOCATION: services/user_profile_service/user_profile_service/routes/profile_routes.py

"""
`/profile*` routes (M4). Thin per Section 6 -- every route resolves the
target user_id from the VERIFIED identity only (`get_current_candidate`),
never from the request body or path, so there is no way for a candidate
to act on someone else's profile/resumes even by malformed input.
"""

from __future__ import annotations

from auth_tokens import TokenPayload
from fastapi import APIRouter, Depends, HTTPException, status

from ..auth_dependency import get_current_candidate
from ..dependencies import get_profile_service, get_resume_service
from ..schemas import (
    ProfileResponse,
    ResumeResponse,
    SelectPrimaryResumeRequest,
    UpdateProfileRequest,
    UploadResumeRequest,
)
from ..services import ProfileService, ResumeNotFoundError, ResumeOwnershipError, ResumeService

router = APIRouter(prefix="/profile")


@router.get("", response_model=ProfileResponse)
async def get_profile(
    identity: TokenPayload = Depends(get_current_candidate),
    service: ProfileService = Depends(get_profile_service),
):
    profile = await service.get_profile(identity.user_id)
    return ProfileResponse.model_validate(profile)


@router.put("", response_model=ProfileResponse)
async def update_profile(
    body: UpdateProfileRequest,
    identity: TokenPayload = Depends(get_current_candidate),
    service: ProfileService = Depends(get_profile_service),
):
    profile = await service.update_profile(identity.user_id, body.model_dump(exclude_unset=True))
    return ProfileResponse.model_validate(profile)


@router.post("/resume", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    body: UploadResumeRequest,
    identity: TokenPayload = Depends(get_current_candidate),
    service: ResumeService = Depends(get_resume_service),
):
    resume = await service.upload_resume(
        user_id=identity.user_id, file_url=body.file_url, parsed_data=body.parsed_data, is_primary=body.is_primary
    )
    return ResumeResponse.model_validate(resume)


@router.get("/resume", response_model=list[ResumeResponse])
async def list_resumes(
    identity: TokenPayload = Depends(get_current_candidate),
    service: ResumeService = Depends(get_resume_service),
):
    resumes = await service.list_resumes(identity.user_id)
    return [ResumeResponse.model_validate(r) for r in resumes]


@router.post("/resume/select-primary", response_model=ResumeResponse)
async def select_primary_resume(
    body: SelectPrimaryResumeRequest,
    identity: TokenPayload = Depends(get_current_candidate),
    service: ResumeService = Depends(get_resume_service),
):
    try:
        resume = await service.select_primary_resume(user_id=identity.user_id, resume_id=body.resume_id)
    except ResumeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ResumeOwnershipError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return ResumeResponse.model_validate(resume)