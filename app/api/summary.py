from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.repositories.summary_repository import SummaryRepository
from app.schemas import SummaryRead

router = APIRouter(tags=["summary"])


@router.get("/summary", response_model=SummaryRead)
def get_summary(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    repository = SummaryRepository(session)
    by_status = repository.projects_by_status(user.id)
    terrains, total_area = repository.terrain_totals(user.id)
    in_progress, completed = repository.progress_counts(user.id)

    return SummaryRead(
        projects=sum(by_status.values()),
        draft_projects=by_status.get("draft", 0),
        active_projects=by_status.get("active", 0),
        archived_projects=by_status.get("archived", 0),
        terrains=terrains,
        total_area_m2=float(total_area),
        materials_total_cost=float(repository.materials_total_cost(user.id)),
        in_progress_projects=in_progress,
        completed_projects=completed,
        materials=repository.materials_count(user.id),
        plans=repository.plans_count(user.id),
    )
