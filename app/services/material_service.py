from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.models import Material, User
from app.repositories.material_repository import MaterialRepository
from app.schemas import MaterialCreate, MaterialUpdate
from app.services.base import ProjectScopedService
from app.services.undo_history import snapshot, undo_history


class MaterialService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.materials = MaterialRepository(session)

    def create(self, project_id: int, data: MaterialCreate) -> Material:
        self._ensure_project_exists(project_id)
        self._ensure_name_is_free(project_id, data.name)

        material = self.materials.save(Material(project_id=project_id, **data.model_dump()))
        self._record("created", "material", project_id, material.id, material.name)

        return material

    def list(self, project_id: int, category: str | None = None) -> list[Material]:
        self._ensure_project_exists(project_id)

        return self.materials.list_by_project(project_id, category=category)

    def get(self, material_id: int) -> Material:
        material = self.materials.get(material_id)

        if material is None or not self._owns(material.project_id):
            raise NotFoundError("Material not found")

        return material

    def update(self, material_id: int, data: MaterialUpdate) -> Material:
        material = self.get(material_id)
        changes = data.model_dump(exclude_unset=True)

        for required in ("name", "unit", "quantity", "unit_cost"):
            if changes.get(required, "") is None:
                del changes[required]

        if "name" in changes and changes["name"] != material.name:
            self._ensure_name_is_free(material.project_id, changes["name"])

        for field, value in changes.items():
            setattr(material, field, value)

        material = self.materials.save(material)
        self._record(
            "updated",
            "material",
            material.project_id,
            material.id,
            material.name,
            fields=sorted(changes),
        )

        return material

    def delete(self, material_id: int) -> None:
        material = self.get(material_id)
        deleted = snapshot("material", material.name, material)
        self.materials.delete(material)
        undo_history.record(deleted, session=self.session)
        self._record("deleted", "material", deleted.project_id, material_id, deleted.label)

    def _ensure_name_is_free(self, project_id: int, name: str) -> None:
        if self.materials.get_by_project_and_name(project_id, name) is not None:
            raise ConflictError("Project already has a material with this name")
