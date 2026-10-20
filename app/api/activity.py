from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.schemas import ActivityPage, ActivityRead
from app.services.activity_service import ActivityService

router = APIRouter(tags=["activity"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ActivityService:
    return ActivityService(session, user)


@router.get("/projects/{project_id}/activity", response_model=ActivityPage)
def list_activity(
    project_id: int,
    entity_type: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    service: ActivityService = Depends(get_service),
):
    items, total = service.page(project_id, page, page_size, entity_type)

    return ActivityPage(
        items=[ActivityRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
