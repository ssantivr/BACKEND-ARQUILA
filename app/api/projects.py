from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.dtos import PropertyType
from app.models import User
from app.schemas import (
    ProjectCreate,
    ProjectPage,
    ProjectRead,
    ProjectSort,
    ProjectStatus,
    ProjectUpdate,
    SortOrder,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])

TOTAL_HEADER = "X-Total-Count"
DEFAULT_PAGE_SIZE = 20


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectService:
    return ProjectService(session, user)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(data: ProjectCreate, service: ProjectService = Depends(get_service)):
    return service.create(data)


@router.get("", response_model=list[ProjectRead] | ProjectPage)
def list_projects(
    response: Response,
    status: ProjectStatus | None = None,
    search: str | None = None,
    q: str | None = Query(default=None, max_length=160),
    property_type: PropertyType | None = Query(default=None, alias="type"),
    archived: bool | None = None,
    sort: ProjectSort = "id",
    order: SortOrder = "asc",
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=100),
    service: ProjectService = Depends(get_service),
):
    """Without page or page_size the answer is the plain list it always was."""
    filters = service.filters(
        status=status, search=search, text=q, property_type=property_type, archived=archived
    )
    paged = page is not None or page_size is not None

    if paged:
        page, page_size = page or 1, page_size or DEFAULT_PAGE_SIZE

    items, total = service.page(filters, sort, order, page, page_size)
    response.headers[TOTAL_HEADER] = str(total)

    if not paged:
        return items

    return ProjectPage(
        items=[ProjectRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, service: ProjectService = Depends(get_service)):
    return service.get(project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    data: ProjectUpdate,
    service: ProjectService = Depends(get_service),
):
    return service.update(project_id, data)


@router.post("/{project_id}/archive", response_model=ProjectRead)
def archive_project(project_id: int, service: ProjectService = Depends(get_service)):
    return service.archive(project_id)


@router.post("/{project_id}/unarchive", response_model=ProjectRead)
def unarchive_project(project_id: int, service: ProjectService = Depends(get_service)):
    return service.unarchive(project_id)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, service: ProjectService = Depends(get_service)):
    service.delete(project_id)
    return Response(status_code=204)
