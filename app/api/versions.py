from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.models import ProjectVersion, User
from app.schemas import ProjectRead, VersionCreate, VersionDetail, VersionRead
from app.services.project_snapshot import contents_of
from app.services.version_service import VersionService

router = APIRouter(tags=["versions"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> VersionService:
    return VersionService(session, user)


def summary_of(version: ProjectVersion) -> dict:
    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_number": version.version_number,
        "label": version.label,
        "created_by": version.created_by,
        "created_at": version.created_at,
        "contents": contents_of(version.snapshot),
    }


@router.get("/projects/{project_id}/versions", response_model=list[VersionRead])
def list_versions(project_id: int, service: VersionService = Depends(get_service)):
    return [summary_of(version) for version in service.list(project_id)]


@router.post(
    "/projects/{project_id}/versions",
    response_model=VersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_version(
    project_id: int,
    data: VersionCreate | None = None,
    service: VersionService = Depends(get_service),
):
    return summary_of(service.create(project_id, data.label if data else None))


@router.get("/versions/{version_id}", response_model=VersionDetail)
def get_version(version_id: int, service: VersionService = Depends(get_service)):
    version = service.get(version_id)

    return {**summary_of(version), "snapshot": version.snapshot}


@router.post("/versions/{version_id}/restore", response_model=ProjectRead)
def restore_version(version_id: int, service: VersionService = Depends(get_service)):
    return service.restore(version_id)
