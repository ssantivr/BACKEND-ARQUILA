from sqlalchemy.orm import Session

from app.models import UserPreferences


class PreferencesRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: int) -> UserPreferences | None:
        return self.session.get(UserPreferences, user_id)

    def save(self, preferences: UserPreferences) -> UserPreferences:
        self.session.add(preferences)
        self.session.commit()
        self.session.refresh(preferences)
        return preferences
