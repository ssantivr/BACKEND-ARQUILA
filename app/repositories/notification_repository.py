from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Notification


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, notification: Notification) -> Notification:
        self.session.add(notification)
        self.session.commit()
        return notification

    def get(self, notification_id: int) -> Notification | None:
        return self.session.get(Notification, notification_id)

    def list_for_user(self, user_id: int, unread_only: bool, limit: int) -> list[Notification]:
        query = select(Notification).where(Notification.user_id == user_id)

        if unread_only:
            query = query.where(Notification.read_at.is_(None))

        return list(self.session.scalars(query.order_by(Notification.id.desc()).limit(limit)))

    def save(self, notification: Notification) -> Notification:
        self.session.add(notification)
        self.session.commit()
        self.session.refresh(notification)
        return notification

    def mark_all_read(self, user_id: int, now: datetime) -> int:
        result = self.session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=now)
        )
        self.session.commit()
        return result.rowcount
