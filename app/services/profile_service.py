from sqlalchemy.orm import Session

from app import storage
from app.errors import InvalidDataError, NotFoundError
from app.models import User
from app.repositories.file_repository import FileRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas import ProfileUpdate
from app.services.base import changes_in


class ProfileService:
    def __init__(self, session: Session, user: User) -> None:
        self.users = UserRepository(session)
        self.files = FileRepository(session)
        self.projects = ProjectRepository(session)
        self.user = user

    def update(self, data: ProfileUpdate) -> User:
        changes = changes_in(data, nullable=("display_name", "avatar_file_id"))

        if "display_name" in changes:
            changes["display_name"] = (changes["display_name"] or "").strip() or None

        if changes.get("avatar_file_id") is not None:
            self._ensure_avatar_is_an_own_image(changes["avatar_file_id"])

        for field, value in changes.items():
            setattr(self.user, field, value)

        self.users.save(self.user)
        self.users.session.refresh(self.user)

        return self.user

    def _ensure_avatar_is_an_own_image(self, file_id: int) -> None:
        file = self.files.get(file_id)

        if file is None or self.projects.get_owned(file.project_id, self.user.id) is None:
            raise NotFoundError("File not found")

        if file.mime_type not in storage.IMAGE_TYPES:
            raise InvalidDataError("The avatar must be a PNG, JPEG or WebP image")
