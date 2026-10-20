from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import storage
from app.errors import ConflictError, InvalidDataError, NotFoundError
from app.models import Project, User
from app.repositories.activity_repository import ActivityRepository
from app.repositories.file_repository import FileRepository
from app.repositories.project_repository import NAME_LENGTH, ProjectFilters, ProjectRepository
from app.schemas import ProjectCreate, ProjectUpdate
from app.services.activity_log import record_activity
from app.services.project_snapshot import SnapshotWriter, take
from app.services.undo_history import undo_history

IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")
STATUS_AFTER_ARCHIVE = "active"
COPY_SUFFIX = " (copia)"


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectService:
    def __init__(self, session: Session, user: User) -> None:
        self.projects = ProjectRepository(session)
        self.files = FileRepository(session)
        self.activity = ActivityRepository(session)
        self.user = user

    def create(self, data: ProjectCreate) -> Project:
        self._ensure_name_is_free(self.user.id, data.name)

        project = Project(owner_id=self.user.id, **data.model_dump())

        if project.status == "archived":
            project.archived_at = utc_now()

        project = self.projects.save(project)
        self._record(project, "created")

        return project

    def list(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> list[Project]:
        return self.projects.list(owner_id=self.user.id, status=status, search=search)

    def page(
        self,
        filters: ProjectFilters,
        sort: str = "id",
        order: str = "asc",
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[Project], int]:
        if page is None and page_size is None:
            return self.projects.page(filters, sort, order)

        offset = ((page or 1) - 1) * (page_size or 0)

        return self.projects.page(filters, sort, order, offset, page_size)

    def filters(self, **values) -> ProjectFilters:
        return ProjectFilters(owner_id=self.user.id, **values)

    def get(self, project_id: int) -> Project:
        project = self.projects.get_owned(project_id, self.user.id)

        if project is None:
            raise NotFoundError("Project not found")

        return project

    def update(self, project_id: int, data: ProjectUpdate) -> Project:
        project = self.get(project_id)
        changes = data.model_dump(exclude_unset=True)

        for required in ("name", "status", "progress"):
            if changes.get(required, "") is None:
                del changes[required]

        if "name" in changes and changes["name"] != project.name:
            self._ensure_name_is_free(project.owner_id, changes["name"])

        if changes.get("cover_file_id") is not None:
            self._ensure_cover_in_project(changes["cover_file_id"], project.id)

        if "status" in changes:
            self._sync_archive_date(project, changes["status"])

        for field, value in changes.items():
            setattr(project, field, value)

        project = self.projects.save(project)
        self._record(project, "updated", fields=sorted(changes))

        return project

    def archive(self, project_id: int) -> Project:
        project = self.get(project_id)

        if project.archived_at is not None and project.status == "archived":
            return project

        previous_status = project.status
        self._sync_archive_date(project, "archived")
        project.status = "archived"
        project = self.projects.save(project)
        self._record(project, "archived", previous_status=previous_status)

        return project

    def unarchive(self, project_id: int) -> Project:
        project = self.get(project_id)

        if project.archived_at is None and project.status != "archived":
            return project

        archived = self.activity.latest(project.id, "archived")
        previous_status = archived.detail.get("previous_status") if archived else None

        project.status = (
            previous_status if previous_status in ("draft", "active") else STATUS_AFTER_ARCHIVE
        )
        project.archived_at = None
        project = self.projects.save(project)
        self._record(project, "unarchived")

        return project

    def duplicate(self, project_id: int, name: str | None = None) -> Project:
        source = self.get(project_id)

        if name is None:
            base = source.name[: NAME_LENGTH - len(COPY_SUFFIX)] + COPY_SUFFIX
            name = self.projects.free_name(self.user.id, base)
        else:
            self._ensure_name_is_free(self.user.id, name)

        copy = Project(
            owner_id=self.user.id,
            name=name,
            description=source.description,
            location=source.location,
            status="draft" if source.status == "archived" else source.status,
            roof=source.roof,
            progress=source.progress,
        )
        session = self.projects.session
        session.add(copy)
        session.flush()

        SnapshotWriter(session, copy).apply(take(source), with_project_fields=False)
        copy = self.projects.save(copy)
        self._record(copy, "duplicated", source_project_id=source.id)

        return copy

    def delete(self, project_id: int) -> None:
        project = self.get(project_id)
        stored_names = [file.storage_path for file in project.files]
        name = project.name

        self.files.detach_avatars([file.id for file in project.files])
        self.projects.delete(project)
        undo_history.forget(project_id, self.projects.session)

        for stored_name in stored_names:
            storage.remove(stored_name)

        # The entries of the project go with it; this one stays in the history of the user.
        record_activity(
            self.projects.session, self.user, None, "deleted", "project", project_id, label=name
        )

    def _sync_archive_date(self, project: Project, status: str) -> None:
        if status == "archived":
            project.archived_at = project.archived_at or utc_now()
        else:
            project.archived_at = None

    def _ensure_cover_in_project(self, file_id: int, project_id: int) -> None:
        file = self.files.get_in_project(file_id, project_id)

        if file is None:
            raise NotFoundError("File not found in this project")

        if file.mime_type not in IMAGE_TYPES:
            raise InvalidDataError("The cover must be a PNG, JPEG or WebP image")

    def _record(self, project: Project, action: str, **detail) -> None:
        record_activity(
            self.projects.session,
            self.user,
            project.id,
            action,
            "project",
            project.id,
            label=project.name,
            **detail,
        )

    def _ensure_name_is_free(self, owner_id: int, name: str) -> None:
        if self.projects.get_by_owner_and_name(owner_id, name) is not None:
            raise ConflictError("Owner already has a project with this name")
