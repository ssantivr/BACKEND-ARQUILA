from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.repositories.activity_repository import ActivityFilters
from app.schemas import ActivityPage, ActivityRead, as_utc
from app.services.activity_log import SOURCE_MODULES, Origin
from app.services.activity_service import ActivityService

router = APIRouter(tags=["activity"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ActivityService:
    return ActivityService(session, user)


def utc_instant(value: datetime | None) -> datetime | None:
    """`value` in UTC; one without an offset is already UTC. A value that leaves the range of
    datetime once shifted to UTC, such as year 1 at +05:00, is rejected instead of failing."""
    if value is None:
        return None

    try:
        return as_utc(value)
    except OverflowError:
        raise HTTPException(status_code=422, detail="Date out of range") from None


@router.get("/projects/{project_id}/activity", response_model=ActivityPage)
def list_activity(
    project_id: int,
    entity_type: str | None = Query(default=None, max_length=40),
    origin: Origin | None = Query(default=None),
    source_module: str | None = Query(default=None, max_length=40),
    user_id: int | None = Query(default=None, ge=1),
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    service: ActivityService = Depends(get_service),
):
    if source_module is not None and source_module not in SOURCE_MODULES:
        raise HTTPException(status_code=422, detail="Unknown source_module")

    since, until = utc_instant(since), utc_instant(until)

    if since is not None and until is not None and since >= until:
        raise HTTPException(status_code=422, detail="'from' must be before 'to'")

    filters = ActivityFilters(
        entity_type=entity_type,
        origin=origin,
        source_module=source_module,
        user_id=user_id,
        since=since,
        until=until,
    )
    items, total = service.page(project_id, page, page_size, filters)

    return ActivityPage(
        items=[ActivityRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
