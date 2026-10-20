from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import UserSession


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user_session: UserSession) -> UserSession:
        self.session.add(user_session)
        self.session.commit()
        return user_session

    def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        return self.session.scalar(select(UserSession).where(UserSession.token_hash == token_hash))

    def delete_by_token_hash(self, token_hash: str) -> None:
        self.session.execute(delete(UserSession).where(UserSession.token_hash == token_hash))
        self.session.commit()

    def delete_for_user(self, user_id: int) -> None:
        self.session.execute(delete(UserSession).where(UserSession.user_id == user_id))
        self.session.commit()

    def delete_others_of_user(self, user_id: int, kept_token_hash: str) -> None:
        self.session.execute(
            delete(UserSession).where(
                UserSession.user_id == user_id, UserSession.token_hash != kept_token_hash
            )
        )
        self.session.commit()

    def delete_expired(self, now: datetime) -> None:
        self.session.execute(delete(UserSession).where(UserSession.expires_at <= now))
        self.session.commit()
