from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.limits import MAX_TEXT_LENGTH
from app.models import User
from app.schemas import MaterialCreate, MaterialRead, MaterialUpdate
from app.services.material_service import MaterialService

router = APIRouter(tags=["materials"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MaterialService:
    return MaterialService(session, user)


@router.post(
    "/projects/{project_id}/materials",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
)
def create_material(
    project_id: int,
    data: MaterialCreate,
    service: MaterialService = Depends(get_service),
):
    return service.create(project_id, data)


@router.get("/projects/{project_id}/materials", response_model=list[MaterialRead])
def list_materials(
    project_id: int,
    category: str | None = Query(default=None, max_length=MAX_TEXT_LENGTH),
    service: MaterialService = Depends(get_service),
):
    return service.list(project_id, category=category)


@router.get("/materials/{material_id}", response_model=MaterialRead)
def get_material(material_id: int, service: MaterialService = Depends(get_service)):
    return service.get(material_id)


@router.patch("/materials/{material_id}", response_model=MaterialRead)
def update_material(
    material_id: int,
    data: MaterialUpdate,
    service: MaterialService = Depends(get_service),
):
    return service.update(material_id, data)


@router.delete("/materials/{material_id}", status_code=204)
def delete_material(material_id: int, service: MaterialService = Depends(get_service)):
    service.delete(material_id)
    return Response(status_code=204)
