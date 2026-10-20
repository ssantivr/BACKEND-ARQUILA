from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Notification, User
from app.repositories.notification_repository import NotificationRepository


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def notify(session: Session, user: User, title: str, body: str | None = None) -> None:
    NotificationRepository(session).add(Notification(user_id=user.id, title=title, body=body))


class NotificationService:
    def __init__(self, session: Session, user: User) -> None:
        self.notifications = NotificationRepository(session)
        self.user = user

    def list(self, unread_only: bool = False, limit: int = 50) -> list[Notification]:
        return self.notifications.list_for_user(self.user.id, unread_only, limit)

    def mark_read(self, notification_id: int) -> Notification:
        notification = self.notifications.get(notification_id)

        if notification is None or notification.user_id != self.user.id:
            raise NotFoundError("Notification not found")

        if notification.read_at is None:
            notification.read_at = utc_now()
            notification = self.notifications.save(notification)

        return notification

    def mark_all_read(self) -> int:
        return self.notifications.mark_all_read(self.user.id, utc_now())
