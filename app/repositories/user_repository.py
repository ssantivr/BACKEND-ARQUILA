from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))

    def list(self) -> list[User]:
        return list(self.session.scalars(select(User).order_by(User.id)))

    def save(self, user: User) -> User:
        self.session.add(user)
        self.session.commit()
        return user

    def replace_hash(self, user: User, verified: str, new: str) -> bool:
        """Only while the hash is still the verified one: a reset can happen meanwhile."""
        changed = self.session.execute(
            update(User)
            .where(User.id == user.id, User.password_hash == verified)
            .values(password_hash=new)
            .execution_options(synchronize_session=False)
        ).rowcount

        if changed != 1:
            self.session.rollback()
            return False

        self.session.commit()
        self.session.refresh(user)
        return True

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user
