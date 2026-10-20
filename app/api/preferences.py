from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.models import User
from app.schemas import PreferencesRead, PreferencesUpdate
from app.services.preferences_service import PreferencesService

router = APIRouter(prefix="/users/me", tags=["preferences"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PreferencesService:
    return PreferencesService(session, user)


@router.get("/preferences", response_model=PreferencesRead)
def get_preferences(service: PreferencesService = Depends(get_service)):
    return service.get()


@router.put("/preferences", response_model=PreferencesRead)
def update_preferences(data: PreferencesUpdate, service: PreferencesService = Depends(get_service)):
    return service.update(data)
