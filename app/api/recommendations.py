from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.limits import MAX_TEXT_LENGTH
from app.models import User
from app.schemas import RecommendationCreate, RecommendationRead, RecommendationSource
from app.services.recommendation_service import RecommendationService

router = APIRouter(tags=["recommendations"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RecommendationService:
    return RecommendationService(session, user)


@router.post(
    "/projects/{project_id}/recommendations",
    response_model=RecommendationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_recommendation(
    project_id: int,
    data: RecommendationCreate,
    service: RecommendationService = Depends(get_service),
):
    return service.create(project_id, data)


@router.get(
    "/projects/{project_id}/recommendations",
    response_model=list[RecommendationRead],
)
def list_recommendations(
    project_id: int,
    category: str | None = Query(default=None, max_length=MAX_TEXT_LENGTH),
    source: RecommendationSource | None = None,
    service: RecommendationService = Depends(get_service),
):
    return service.list(project_id, category=category, source=source)


@router.post(
    "/projects/{project_id}/recommendations/generate",
    response_model=list[RecommendationRead],
)
def generate_recommendations(
    project_id: int, service: RecommendationService = Depends(get_service)
):
    return service.generate(project_id)


@router.delete("/recommendations/{recommendation_id}", status_code=204)
def delete_recommendation(
    recommendation_id: int, service: RecommendationService = Depends(get_service)
):
    service.delete(recommendation_id)
    return Response(status_code=204)
