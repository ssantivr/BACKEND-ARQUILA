from sqlalchemy.orm import Session

from app import storage
from app.errors import ConflictError, InvalidDataError, NotFoundError
from app.limits import MAX_TEXT_LENGTH
from app.models import Project, User
from app.repositories.project_repository import ProjectRepository
from app.schemas import ProjectCreate, ProjectUpdate
from app.services.undo_history import undo_history


class ProjectService:
    def __init__(self, session: Session, user: User) -> None:
        self.projects = ProjectRepository(session)
        self.user = user

    def create(self, data: ProjectCreate) -> Project:
        self._ensure_name_is_free(self.user.id, data.name)

        return self.projects.save(Project(owner_id=self.user.id, **data.model_dump()))

    def list(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> list[Project]:
        return self.projects.list(owner_id=self.user.id, status=status, search=search)

    def get(self, project_id: int) -> Project:
        project = self.projects.get_owned(project_id, self.user.id)

        if project is None:
            raise NotFoundError("Project not found")

        return project

    def update(self, project_id: int, data: ProjectUpdate) -> Project:
        project = self.get(project_id)
        changes = data.model_dump(exclude_unset=True)

        for required in ("name", "status"):
            if changes.get(required, "") is None:
                del changes[required]

        # An older text that is longer may be sent back as it was: only a new one has the limit.
        for field in ("description", "location"):
            value = changes.get(field)

            if value and len(value) > MAX_TEXT_LENGTH and value != getattr(project, field):
                raise InvalidDataError(f"The text exceeds {MAX_TEXT_LENGTH} characters")

        if "name" in changes and changes["name"] != project.name:
            self._ensure_name_is_free(project.owner_id, changes["name"])

        for field, value in changes.items():
            setattr(project, field, value)

        return self.projects.save(project)

    def delete(self, project_id: int) -> None:
        project = self.get(project_id)
        stored_names = [file.storage_path for file in project.files]

        self.projects.delete(project)
        undo_history.forget(project_id, self.projects.session)

        for stored_name in stored_names:
            storage.remove(stored_name)

    def _ensure_name_is_free(self, owner_id: int, name: str) -> None:
        if self.projects.get_by_owner_and_name(owner_id, name) is not None:
            raise ConflictError("Owner already has a project with this name")
