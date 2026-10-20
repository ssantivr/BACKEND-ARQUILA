from sqlalchemy.orm import Session

from app.models import ActivityEntry, User
from app.repositories.activity_repository import ActivityRepository
from app.services.base import ProjectScopedService


class ActivityService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.activity = ActivityRepository(session)

    def page(
        self, project_id: int, page: int, page_size: int, entity_type: str | None = None
    ) -> tuple[list[ActivityEntry], int]:
        self._ensure_project_exists(project_id)

        return self.activity.page_by_project(
            project_id, (page - 1) * page_size, page_size, entity_type
        )
