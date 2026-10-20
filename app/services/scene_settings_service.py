from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import SceneSettings, User, WalkthroughPoint
from app.repositories.scene_repository import SceneRepository
from app.schemas import SceneSettingsUpdate, WalkthroughPointCreate, WalkthroughPointUpdate
from app.services.base import ProjectScopedService, changes_in


class SceneSettingsService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.scenes = SceneRepository(session)

    def get_settings(self, project_id: int) -> SceneSettings:
        """The saved settings, or empty ones while the project has none."""
        self._ensure_project_exists(project_id)

        return self._settings(project_id)

    def update_settings(self, project_id: int, data: SceneSettingsUpdate) -> SceneSettings:
        self._ensure_project_exists(project_id)

        settings = self._settings(project_id)
        changes = changes_in(data)

        for field, value in changes.items():
            setattr(settings, field, value)

        settings = self.scenes.save(settings)
        self._record(
            "updated", "scene_settings", project_id, project_id, "Scene", fields=sorted(changes)
        )

        return settings

    def list_points(self, project_id: int) -> list[WalkthroughPoint]:
        self._ensure_project_exists(project_id)

        return self.scenes.list_points(project_id)

    def create_point(self, project_id: int, data: WalkthroughPointCreate) -> WalkthroughPoint:
        self._ensure_project_exists(project_id)

        point = self.scenes.save(WalkthroughPoint(project_id=project_id, **data.model_dump()))
        self._record("created", "walkthrough_point", project_id, point.id, point.name)

        return point

    def get_point(self, point_id: int) -> WalkthroughPoint:
        point = self.scenes.get_point(point_id)

        if point is None or not self._owns(point.project_id):
            raise NotFoundError("Walkthrough point not found")

        return point

    def update_point(self, point_id: int, data: WalkthroughPointUpdate) -> WalkthroughPoint:
        point = self.get_point(point_id)
        changes = changes_in(data)

        for field, value in changes.items():
            setattr(point, field, value)

        point = self.scenes.save(point)
        self._record(
            "updated",
            "walkthrough_point",
            point.project_id,
            point.id,
            point.name,
            fields=sorted(changes),
        )

        return point

    def delete_point(self, point_id: int) -> None:
        point = self.get_point(point_id)
        project_id, name = point.project_id, point.name
        self.scenes.delete(point)
        self._record("deleted", "walkthrough_point", project_id, point_id, name)

    def _settings(self, project_id: int) -> SceneSettings:
        return self.scenes.get_settings(project_id) or SceneSettings(
            project_id=project_id, lighting={}, camera_presets=[]
        )
