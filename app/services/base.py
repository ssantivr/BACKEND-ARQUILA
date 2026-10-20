from collections.abc import Collection
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Room, User
from app.repositories.project_repository import ProjectRepository
from app.services.activity_log import record_activity


class ProjectScopedService:
    def __init__(self, session: Session, user: User) -> None:
        self.session = session
        self.user = user
        self.projects = ProjectRepository(session)

    def _owns(self, project_id: int) -> bool:
        return self.projects.get_owned(project_id, self.user.id) is not None

    def _ensure_project_exists(self, project_id: int) -> None:
        if not self._owns(project_id):
            raise NotFoundError("Project not found")

    def _record(
        self,
        action: str,
        entity_type: str,
        project_id: int,
        entity_id: int,
        label: str,
        **detail: Any,
    ) -> None:
        record_activity(
            self.session,
            self.user,
            project_id,
            action,
            entity_type,
            entity_id,
            label=label,
            **detail,
        )


class ApiScopedService(ProjectScopedService):
    """Base of the /api/v1 services, whose messages reach the user as they are."""

    def _require_project(self, project_id: int) -> None:
        if not self._owns(project_id):
            raise NotFoundError("Proyecto no encontrado.")

    def _require_room(self, room_id: int, project_id: int) -> Room:
        room = self.session.get(Room, room_id)

        if room is None or room.project_id != project_id:
            raise NotFoundError("Ese cuarto no pertenece a este proyecto.")

        return room


def changes_in(data: BaseModel, nullable: Collection[str] = ()) -> dict[str, Any]:
    """Fields the client sent. A null only counts for the fields that can be emptied."""
    return {
        field: value
        for field, value in data.model_dump(exclude_unset=True).items()
        if value is not None or field in nullable
    }
