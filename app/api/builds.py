from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.extraction.providers import Extractor, get_extractor
from app.extraction.schemas import BuildApply, BuildCreate, BuildRead
from app.models import User
from app.services.build_service import BuildService, to_build_read

router = APIRouter(tags=["builds"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> BuildService:
    return BuildService(session, user)


@router.post(
    "/projects/{project_id}/builds",
    response_model=BuildRead,
    status_code=status.HTTP_201_CREATED,
)
def create_build(
    project_id: int,
    data: BuildCreate,
    service: BuildService = Depends(get_service),
    extractor: Extractor | None = Depends(get_extractor),
):
    return to_build_read(service.create_build(project_id, data, extractor))


@router.get("/projects/{project_id}/builds", response_model=list[BuildRead])
def list_builds(project_id: int, service: BuildService = Depends(get_service)):
    return [to_build_read(build) for build in service.list_builds(project_id)]


@router.post("/builds/{build_id}/apply", response_model=BuildRead)
def apply_build(build_id: int, data: BuildApply, service: BuildService = Depends(get_service)):
    return to_build_read(service.apply_build(build_id, data))


@router.post("/builds/{build_id}/undo", response_model=BuildRead)
def undo_build(build_id: int, service: BuildService = Depends(get_service)):
    return to_build_read(service.undo_build(build_id))
