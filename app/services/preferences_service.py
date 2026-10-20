from sqlalchemy.orm import Session

from app.models import User, UserPreferences
from app.repositories.preferences_repository import PreferencesRepository
from app.schemas import PreferencesUpdate
from app.services.base import changes_in

DEFAULTS = {
    "theme": "auto",
    "units": "metric",
    "density": "comfortable",
    "reduce_motion": False,
    "preview_quality": "medium",
    "camera_defaults": {},
    "notifications": {},
}


class PreferencesService:
    def __init__(self, session: Session, user: User) -> None:
        self.preferences = PreferencesRepository(session)
        self.user = user

    def get(self) -> UserPreferences:
        """The stored preferences, or the defaults when the user never saved any."""
        return self.preferences.get(self.user.id) or UserPreferences(
            user_id=self.user.id, **DEFAULTS
        )

    def update(self, data: PreferencesUpdate) -> UserPreferences:
        preferences = self.preferences.get(self.user.id) or UserPreferences(
            user_id=self.user.id, **DEFAULTS
        )

        for field, value in changes_in(data).items():
            setattr(preferences, field, value)

        return self.preferences.save(preferences)
