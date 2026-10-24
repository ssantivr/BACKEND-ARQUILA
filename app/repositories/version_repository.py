from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProjectVersion


class VersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, version_id: int) -> ProjectVersion | None:
        return self.session.get(ProjectVersion, version_id)

    def list_by_project(self, project_id: int) -> list[ProjectVersion]:
        query = select(ProjectVersion).where(ProjectVersion.project_id == project_id)
        return list(self.session.scalars(query.order_by(ProjectVersion.version_number.desc())))

    def next_number(self, project_id: int) -> int:
        last = self.session.scalar(
            select(func.max(ProjectVersion.version_number)).where(
                ProjectVersion.project_id == project_id
            )
        )
        return (last or 0) + 1

    def add(self, version: ProjectVersion) -> ProjectVersion:
        # Flushed, not committed: the caller ends the transaction.
        self.session.add(version)
        self.session.flush()
        return version

    def save(self, version: ProjectVersion) -> ProjectVersion:
        self.session.add(version)
        self.session.commit()
        self.session.refresh(version)
        return version
