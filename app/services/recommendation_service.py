from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Recommendation, User
from app.repositories.material_repository import MaterialRepository
from app.repositories.recommendation_repository import RecommendationRepository
from app.repositories.terrain_repository import TerrainRepository
from app.schemas import RecommendationCreate
from app.services import recommendation_rules
from app.services.base import ProjectScopedService


class RecommendationService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.recommendations = RecommendationRepository(session)
        self.terrains = TerrainRepository(session)
        self.materials = MaterialRepository(session)

    def create(self, project_id: int, data: RecommendationCreate) -> Recommendation:
        self._ensure_project_exists(project_id)

        recommendation = self.recommendations.save(
            Recommendation(project_id=project_id, source="user", **data.model_dump())
        )
        self._record(
            "created", "recommendation", project_id, recommendation.id, recommendation.category
        )

        return recommendation

    def list(
        self,
        project_id: int,
        category: str | None = None,
        source: str | None = None,
    ) -> list[Recommendation]:
        self._ensure_project_exists(project_id)

        return self.recommendations.list_by_project(project_id, category=category, source=source)

    def generate(self, project_id: int) -> list[Recommendation]:
        self._ensure_project_exists(project_id)

        suggestions = recommendation_rules.evaluate(
            self.terrains.list_by_project(project_id),
            self.materials.list_by_project(project_id),
        )

        return self.recommendations.replace_by_source(
            project_id,
            "system",
            [
                Recommendation(
                    project_id=project_id,
                    source="system",
                    category=category,
                    content=content,
                    priority=priority,
                )
                for category, content, priority in suggestions
            ],
        )

    def delete(self, recommendation_id: int) -> None:
        recommendation = self.recommendations.get(recommendation_id)

        if recommendation is None or not self._owns(recommendation.project_id):
            raise NotFoundError("Recommendation not found")

        project_id, category = recommendation.project_id, recommendation.category
        self.recommendations.delete(recommendation)
        self._record("deleted", "recommendation", project_id, recommendation_id, category)
