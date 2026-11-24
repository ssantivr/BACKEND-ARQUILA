from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Material, Plan, Project, Terrain


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

    def plans_count(self, owner_id: int) -> int:
        return self.session.scalar(
            select(func.count(Plan.id))
            .join(Project, Plan.project_id == Project.id)
            .where(Project.owner_id == owner_id)
        )

    def materials_total_cost(self, owner_id: int) -> Decimal:
        return self.session.scalar(
            select(func.coalesce(func.sum(Material.quantity * Material.unit_cost), 0))
            .join(Project, Material.project_id == Project.id)
            .where(Project.owner_id == owner_id)
        )
