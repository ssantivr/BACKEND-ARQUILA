from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Elevation, User
from app.repositories.elevation_repository import ElevationRepository
from app.repositories.file_repository import FileRepository
from app.schemas import ElevationCreate, ElevationUpdate
from app.services.base import ProjectScopedService
from app.services.undo_history import snapshot, undo_history


class ElevationService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.elevations = ElevationRepository(session)
        self.files = FileRepository(session)

    def create(self, project_id: int, data: ElevationCreate) -> Elevation:
        self._ensure_project_exists(project_id)
        self._ensure_file_in_project(data.file_id, project_id)

        elevation = self.elevations.save(Elevation(project_id=project_id, **data.model_dump()))
        self._record("created", "elevation", project_id, elevation.id, elevation.title)

        return elevation

    def list(self, project_id: int, orientation: str | None = None) -> list[Elevation]:
        self._ensure_project_exists(project_id)

        return self.elevations.list_by_project(project_id, orientation=orientation)

    def get(self, elevation_id: int) -> Elevation:
        elevation = self.elevations.get(elevation_id)

        if elevation is None or not self._owns(elevation.project_id):
            raise NotFoundError("Elevation not found")

        return elevation

    def update(self, elevation_id: int, data: ElevationUpdate) -> Elevation:
        elevation = self.get(elevation_id)

        changes = data.model_dump(exclude_unset=True)

        for required in ("title", "orientation"):
            if changes.get(required, "") is None:
                del changes[required]

        self._ensure_file_in_project(changes.get("file_id"), elevation.project_id)

        for field, value in changes.items():
            setattr(elevation, field, value)

        elevation = self.elevations.save(elevation)
        self._record(
            "updated",
            "elevation",
            elevation.project_id,
            elevation.id,
            elevation.title,
            fields=sorted(changes),
        )

        return elevation

    def delete(self, elevation_id: int) -> None:
        elevation = self.get(elevation_id)
        deleted = snapshot("elevation", elevation.title, elevation)
        self.elevations.delete(elevation)
        undo_history.record(deleted, session=self.session)
        self._record("deleted", "elevation", deleted.project_id, elevation_id, deleted.label)

    def _ensure_file_in_project(self, file_id: int | None, project_id: int) -> None:
        if file_id is not None and self.files.get_in_project(file_id, project_id) is None:
            raise NotFoundError("File not found in this project")
