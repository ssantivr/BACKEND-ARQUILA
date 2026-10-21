from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO

from sqlalchemy.orm import Session

from app import storage
from app.errors import NotFoundError
from app.models import File, FileContent, User
from app.repositories.file_repository import FileRepository
from app.services.base import ProjectScopedService

AVATAR_REJECTION = "The avatar must be a PNG, JPEG or WebP image"


def clean_filename(filename: str | None) -> str:
    name = PureWindowsPath(PurePosixPath(filename or "").name).name.strip()
    return name[:255] or "file"


class FileService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.files = FileRepository(session)

    def create(self, project_id: int, filename: str | None, stream: BinaryIO) -> File:
        self._ensure_project_exists(project_id)

        file = self._store(project_id, filename, stream)
        self._record("created", "file", project_id, file.id, file.filename)

        return file

    def create_avatar(self, filename: str | None, stream: BinaryIO) -> File:
        """A picture of the user, outside every project."""
        return self._store(None, filename, stream, storage.IMAGE_TYPES, AVATAR_REJECTION)

    def _store(
        self,
        project_id: int | None,
        filename: str | None,
        stream: BinaryIO,
        allowed: tuple[str, ...] | None = None,
        rejection: str | None = None,
    ) -> File:
        if storage.keeps_files_in_database():
            data, mime_type = storage.read(stream, allowed, rejection)

            return self.files.save(
                File(
                    project_id=project_id,
                    uploaded_by=self.user.id,
                    filename=clean_filename(filename),
                    storage_path=storage.DATABASE_PATH,
                    mime_type=mime_type,
                    size_bytes=len(data),
                    content=FileContent(data=data),
                )
            )

        stored_name, mime_type, size = storage.store(stream, allowed, rejection)

        try:
            return self.files.save(
                File(
                    project_id=project_id,
                    uploaded_by=self.user.id,
                    filename=clean_filename(filename),
                    storage_path=stored_name,
                    mime_type=mime_type,
                    size_bytes=size,
                )
            )
        except BaseException:
            storage.remove(stored_name)
            raise

    def list(self, project_id: int) -> list[File]:
        self._ensure_project_exists(project_id)

        return self.files.list_by_project(project_id)

    def get(self, file_id: int) -> File:
        file = self.files.get(file_id)

        if file is None or not self._can_open(file):
            raise NotFoundError("File not found")

        return file

    def _can_open(self, file: File) -> bool:
        if file.project_id is None:
            return file.uploaded_by == self.user.id

        return self._owns(file.project_id)

    def content_data(self, file: File) -> bytes | None:
        if file.storage_path != storage.DATABASE_PATH:
            return None

        if file.content is None:
            raise NotFoundError("File content is missing from storage")

        return file.content.data

    def content_path(self, file: File) -> Path:
        path = storage.path_for(file.storage_path)

        if not path.is_file():
            raise NotFoundError("File content is missing from storage")

        return path

    def delete(self, file_id: int) -> None:
        file = self.get(file_id)
        stored_name = file.storage_path
        project_id, filename = file.project_id, file.filename

        self.files.delete(file)
        storage.remove(stored_name)

        if project_id is not None:
            self._record("deleted", "file", project_id, file_id, filename)
