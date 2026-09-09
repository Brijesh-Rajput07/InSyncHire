# LOCATION: services/job_service/job_service/routes/public_routes.py

"""`/public/jobs` -- no authentication required (Section: "Public
listing on candidate job board"). See PublicBoardService's docstring
for the interim-implementation caveat."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import get_public_board_service
from ..schemas import PublicJobResponse
from ..services import PublicBoardService

router = APIRouter(prefix="/public")


@router.get("/jobs", response_model=list[PublicJobResponse])
async def list_public_jobs(service: PublicBoardService = Depends(get_public_board_service)):
    jobs = await service.list_open_jobs()
    return [PublicJobResponse(**j) for j in jobs]