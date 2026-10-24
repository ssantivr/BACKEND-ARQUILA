from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Project, ProjectVersion, User
from app.repositories.version_repository import VersionRepository
from app.services.base import ProjectScopedService
from app.services.project_snapshot import SnapshotWriter, check_format, take
from app.services.undo_history import undo_history


class VersionService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.versions = VersionRepository(session)

    def list(self, project_id: int) -> list[ProjectVersion]:
        self._ensure_project_exists(project_id)

        return self.versions.list_by_project(project_id)

    def create(self, project_id: int, label: str | None = None) -> ProjectVersion:
        project = self._project(project_id)
        version = self._save(project, label)
        self._record(
            "version_saved",
            "version",
            project.id,
            version.id,
            label or f"Version {version.version_number}",
            version_number=version.version_number,
        )

        return version

    def get(self, version_id: int) -> ProjectVersion:
        version = self.versions.get(version_id)

        if version is None or not self._owns(version.project_id):
            raise NotFoundError("Version not found")

        return version

    def restore(self, version_id: int) -> Project:
        version = self.get(version_id)
        project = self._project(version.project_id)
        # Checked before the backup, so that a version that cannot be read leaves nothing behind.
        check_format(version.snapshot)

        # The current state is saved first, so that a restore can itself be undone.
        backup = self._save(project, f"Before restoring version {version.version_number}")

        SnapshotWriter(self.session, project).apply(version.snapshot)
        self.session.commit()
        self.session.refresh(project)

        # What was deleted belongs to a state that no longer exists.
        undo_history.forget(project.id, self.session)
        self._record(
            "version_restored",
            "version",
            project.id,
            version.id,
            version.label or f"Version {version.version_number}",
            version_number=version.version_number,
            backup_version_id=backup.id,
        )

        return project

    def _save(self, project: Project, label: str | None) -> ProjectVersion:
        return self.versions.save(
            ProjectVersion(
                project_id=project.id,
                version_number=self.versions.next_number(project.id),
                label=label,
                snapshot=take(project),
                created_by=self.user.id,
            )
        )

    def _project(self, project_id: int) -> Project:
        project = self.projects.get_owned(project_id, self.user.id)

        if project is None:
            raise NotFoundError("Project not found")

        return project
