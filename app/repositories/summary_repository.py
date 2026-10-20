from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Material, Plan, Project, Terrain
from app.repositories.project_repository import is_archived


class SummaryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def projects_by_status(self, owner_id: int) -> dict[str, int]:
        rows = self.session.execute(
            select(Project.status, func.count(Project.id))
            .where(Project.owner_id == owner_id)
            .group_by(Project.status)
        )
        return {status: count for status, count in rows}

    def terrain_totals(self, owner_id: int) -> tuple[int, Decimal]:
        count, area = self.session.execute(
            select(func.count(Terrain.id), func.coalesce(func.sum(Terrain.area_m2), 0))
            .join(Project, Terrain.project_id == Project.id)
            .where(Project.owner_id == owner_id)
        ).one()
        return count, area

    def materials_total_cost(self, owner_id: int) -> Decimal:
        return self.session.scalar(
            select(func.coalesce(func.sum(Material.quantity * Material.unit_cost), 0))
            .join(Project, Material.project_id == Project.id)
            .where(Project.owner_id == owner_id)
        )

    def progress_counts(self, owner_id: int) -> tuple[int, int]:
        """Projects being worked on (active, not finished) and finished ones (at 100 %)."""
        in_progress, completed = self.session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (Project.status == "active")
                                & (Project.progress < 100)
                                & ~is_archived(),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(case((Project.progress == 100, 1), else_=0)), 0),
            ).where(Project.owner_id == owner_id)
        ).one()
        return int(in_progress), int(completed)

    def count_in_projects(self, model: type[Base], owner_id: int) -> int:
        return self.session.scalar(
            select(func.count(model.id))
            .join(Project, model.project_id == Project.id)
            .where(Project.owner_id == owner_id)
        )

    def materials_count(self, owner_id: int) -> int:
        return self.count_in_projects(Material, owner_id)

    def plans_count(self, owner_id: int) -> int:
        return self.count_in_projects(Plan, owner_id)
