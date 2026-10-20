from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.schemas import NotificationRead, NotificationsMarked
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> NotificationService:
    return NotificationService(session, user)


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    service: NotificationService = Depends(get_service),
):
    return service.list(unread_only=unread, limit=limit)


@router.post("/read-all", response_model=NotificationsMarked)
def mark_all_notifications_read(service: NotificationService = Depends(get_service)):
    return NotificationsMarked(updated=service.mark_all_read())


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: int, service: NotificationService = Depends(get_service)
):
    return service.mark_read(notification_id)
