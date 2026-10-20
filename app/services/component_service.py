from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import StructuralComponent, User
from app.repositories.component_repository import ComponentRepository
from app.repositories.plan_repository import PlanRepository
from app.schemas import ComponentCreate, ComponentUpdate
from app.services.base import ProjectScopedService
from app.services.undo_history import snapshot, undo_history


class ComponentService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.components = ComponentRepository(session)
        self.plans = PlanRepository(session)

    def create(self, project_id: int, data: ComponentCreate) -> StructuralComponent:
        self._ensure_project_exists(project_id)
        self._ensure_plan_in_project(data.plan_id, project_id)

        component = self.components.save(
            StructuralComponent(project_id=project_id, **data.model_dump())
        )
        self._record("created", "component", project_id, component.id, component.name)

        return component

    def list(self, project_id: int, kind: str | None = None) -> list[StructuralComponent]:
        self._ensure_project_exists(project_id)

        return self.components.list_by_project(project_id, kind)

    def get(self, component_id: int) -> StructuralComponent:
        component = self.components.get(component_id)

        if component is None or not self._owns(component.project_id):
            raise NotFoundError("Component not found")

        return component

    def update(self, component_id: int, data: ComponentUpdate) -> StructuralComponent:
        component = self.get(component_id)
        changes = {
            field: value
            for field, value in data.model_dump(exclude_unset=True).items()
            if value is not None
        }

        if "plan_id" in changes:
            self._ensure_plan_in_project(changes["plan_id"], component.project_id)

        for field, value in changes.items():
            setattr(component, field, value)

        component = self.components.save(component)
        self._record(
            "updated",
            "component",
            component.project_id,
            component.id,
            component.name,
            fields=sorted(changes),
        )

        return component

    def delete(self, component_id: int) -> None:
        component = self.get(component_id)
        deleted = snapshot("component", component.name, component)
        self.components.delete(component)
        undo_history.record(deleted, session=self.session)
        self._record("deleted", "component", deleted.project_id, component_id, deleted.label)

    def _ensure_plan_in_project(self, plan_id: int, project_id: int) -> None:
        plan = self.plans.get(plan_id)

        if plan is None or plan.project_id != project_id:
            raise NotFoundError("Plan not found in this project")
