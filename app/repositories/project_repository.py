from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AIExtraction, Project


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, project_id: int) -> Project | None:
        return self.session.get(Project, project_id)

    def get_owned(self, project_id: int, owner_id: int) -> Project | None:
        project = self.get(project_id)
        return project if project is not None and project.owner_id == owner_id else None

    def get_by_owner_and_name(self, owner_id: int, name: str) -> Project | None:
        return self.session.scalar(
            select(Project).where(Project.owner_id == owner_id, Project.name == name)
        )

    def list(
        self,
        owner_id: int,
        status: str | None = None,
        search: str | None = None,
    ) -> list[Project]:
        query = select(Project).where(Project.owner_id == owner_id).order_by(Project.id)

        if status is not None:
            query = query.where(Project.status == status)

        if search:
            query = query.where(Project.name.icontains(search, autoescape=True))

        return list(self.session.scalars(query))

    def save(self, project: Project) -> Project:
        self.session.add(project)
        self.session.commit()
        self.session.refresh(project)
        return project

    def delete(self, project: Project) -> None:
        # The rows stay for the quota, without anything read from the documents. This waits for
        # a reading that is being saved, and one that ends later finds no project to write to.
        self.session.execute(
            update(AIExtraction)
            .where(AIExtraction.project_id == project.id)
            .values(project_id=None, proposal=None, snapshot=None)
        )
        self.session.delete(project)
        self.session.commit()
