from typing import BinaryIO

from sqlalchemy.orm import Session

from app import storage
from app.errors import InvalidDataError
from app.models import User
from app.repositories.file_repository import FileRepository
from app.repositories.user_repository import UserRepository
from app.schemas import ProfileUpdate
from app.services.base import changes_in
from app.services.file_service import AVATAR_REJECTION, FileService


class ProfileService:
    def __init__(self, session: Session, user: User) -> None:
        self.users = UserRepository(session)
        self.files = FileRepository(session)
        self.file_service = FileService(session, user)
        self.user = user

    def update(self, data: ProfileUpdate) -> User:
        changes = changes_in(data, nullable=("display_name", "avatar_file_id"))
        previous_avatar = self.user.avatar_file_id

        if "display_name" in changes:
            changes["display_name"] = (changes["display_name"] or "").strip() or None

        if changes.get("avatar_file_id") is not None:
            self._ensure_avatar_is_an_own_image(changes["avatar_file_id"])

        for field, value in changes.items():
            setattr(self.user, field, value)

        return self._save(previous_avatar)

    def upload_avatar(self, filename: str | None, stream: BinaryIO) -> User:
        previous_avatar = self.user.avatar_file_id
        avatar = self.file_service.create_avatar(filename, stream)
        self.user.avatar_file_id = avatar.id

        return self._save(previous_avatar)

    def _save(self, previous_avatar: int | None) -> User:
        self.users.save(self.user)

        if previous_avatar is not None and previous_avatar != self.user.avatar_file_id:
            self._release(previous_avatar)

        self.users.session.refresh(self.user)

        return self.user

    def _release(self, file_id: int) -> None:
        """Delete a replaced picture that was uploaded as an avatar; project files stay."""
        file = self.files.get(file_id)

        if file is not None and file.project_id is None and file.uploaded_by == self.user.id:
            stored_name = file.storage_path
            self.files.delete(file)
            storage.remove(stored_name)

    def _ensure_avatar_is_an_own_image(self, file_id: int) -> None:
        file = self.file_service.get(file_id)

        if file.mime_type not in storage.IMAGE_TYPES:
            raise InvalidDataError(AVATAR_REJECTION)
