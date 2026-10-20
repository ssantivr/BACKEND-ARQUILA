from typing import Any

from sqlalchemy.orm import Session

from app.models import ActivityEntry, User
from app.repositories.activity_repository import ActivityRepository


def record_activity(
    session: Session,
    user: User,
    project_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    **detail: Any,
) -> None:
    ActivityRepository(session).add(
        ActivityEntry(
            project_id=project_id,
            user_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
        )
    )
