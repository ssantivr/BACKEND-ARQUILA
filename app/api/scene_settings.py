from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.schemas import (
    SceneSettingsRead,
    SceneSettingsUpdate,
    WalkthroughPointCreate,
    WalkthroughPointRead,
    WalkthroughPointUpdate,
)
from app.services.scene_settings_service import SceneSettingsService

router = APIRouter(tags=["scene"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SceneSettingsService:
    return SceneSettingsService(session, user)


@router.get("/projects/{project_id}/scene-settings", response_model=SceneSettingsRead)
def get_scene_settings(project_id: int, service: SceneSettingsService = Depends(get_service)):
    return service.get_settings(project_id)


@router.put("/projects/{project_id}/scene-settings", response_model=SceneSettingsRead)
def update_scene_settings(
    project_id: int,
    data: SceneSettingsUpdate,
    service: SceneSettingsService = Depends(get_service),
):
    return service.update_settings(project_id, data)


@router.get("/projects/{project_id}/walkthrough-points", response_model=list[WalkthroughPointRead])
def list_walkthrough_points(project_id: int, service: SceneSettingsService = Depends(get_service)):
    return service.list_points(project_id)


@router.post(
    "/projects/{project_id}/walkthrough-points",
    response_model=WalkthroughPointRead,
    status_code=status.HTTP_201_CREATED,
)
def create_walkthrough_point(
    project_id: int,
    data: WalkthroughPointCreate,
    service: SceneSettingsService = Depends(get_service),
):
    return service.create_point(project_id, data)


@router.get("/walkthrough-points/{point_id}", response_model=WalkthroughPointRead)
def get_walkthrough_point(point_id: int, service: SceneSettingsService = Depends(get_service)):
    return service.get_point(point_id)


@router.patch("/walkthrough-points/{point_id}", response_model=WalkthroughPointRead)
def update_walkthrough_point(
    point_id: int,
    data: WalkthroughPointUpdate,
    service: SceneSettingsService = Depends(get_service),
):
    return service.update_point(point_id, data)


@router.delete("/walkthrough-points/{point_id}", status_code=204)
def delete_walkthrough_point(point_id: int, service: SceneSettingsService = Depends(get_service)):
    service.delete_point(point_id)
    return Response(status_code=204)
