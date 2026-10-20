from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import Project, Property

NAME_LENGTH = 160
SORT_COLUMNS = {
    "id": Project.id,
    "name": func.lower(Project.name),
    "created_at": Project.created_at,
    "updated_at": Project.updated_at,
    "status": Project.status,
    "progress": Project.progress,
}


def is_archived() -> ColumnElement[bool]:
    return or_(Project.archived_at.is_not(None), Project.status == "archived")


@dataclass(frozen=True)
class ProjectFilters:
    owner_id: int
    status: str | None = None
    search: str | None = None
    text: str | None = None
    property_type: str | None = None
    archived: bool | None = None

    def conditions(self) -> list[ColumnElement[bool]]:
        conditions = [Project.owner_id == self.owner_id]

        if self.status is not None:
            conditions.append(Project.status == self.status)

        if self.search:
            conditions.append(Project.name.icontains(self.search, autoescape=True))

        if self.text:
            conditions.append(
                or_(
                    *(
                        column.icontains(self.text, autoescape=True)
                        for column in (Project.name, Project.description, Project.location)
                    )
                )
            )

        if self.property_type is not None:
            conditions.append(
                exists().where(
                    and_(
                        Property.project_id == Project.id,
                        Property.property_type == self.property_type,
                    )
                )
            )

        if self.archived is True:
            conditions.append(is_archived())
        elif self.archived is False:
            conditions.append(~is_archived())

        return conditions


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
        items, _ = self.page(ProjectFilters(owner_id=owner_id, status=status, search=search))
        return items

    def page(
        self,
        filters: ProjectFilters,
        sort: str = "id",
        order: str = "asc",
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[Project], int]:
        conditions = filters.conditions()
        total = self.session.scalar(select(func.count(Project.id)).where(*conditions))

        column = SORT_COLUMNS[sort]
        direction = column.desc() if order == "desc" else column.asc()
        tie_breaker = Project.id.desc() if order == "desc" else Project.id.asc()
        query = select(Project).where(*conditions).order_by(direction, tie_breaker)

        if offset:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        return list(self.session.scalars(query)), total

    def free_name(self, owner_id: int, name: str) -> str:
        """The name itself, or with the first free number after it, within the length limit."""
        candidate = name[:NAME_LENGTH]
        copy = 2

        while self.get_by_owner_and_name(owner_id, candidate) is not None:
            suffix = f" ({copy})"
            candidate = name[: NAME_LENGTH - len(suffix)] + suffix
            copy += 1

        return candidate

    def save(self, project: Project) -> Project:
        self.session.add(project)
        self.session.commit()
        self.session.refresh(project)
        return project

    def delete(self, project: Project) -> None:
        self.session.delete(project)
        self.session.commit()
