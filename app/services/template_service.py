from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Material, Plan, Project, Room, StructuralComponent, Terrain, User
from app.repositories.project_repository import ProjectRepository
from app.services.project_templates import (
    COLUMN_SIDE_M,
    TEMPLATES,
    ProjectTemplate,
    corner_columns,
)


class TemplateService:
    def __init__(self, session: Session, user: User) -> None:
        self.session = session
        self.user = user
        self.projects = ProjectRepository(session)

    def list(self) -> tuple[ProjectTemplate, ...]:
        return TEMPLATES

    def create_project(self, template_id: str) -> Project:
        template = next((item for item in TEMPLATES if item.id == template_id), None)

        if template is None:
            raise NotFoundError("Template not found")

        project = Project(
            owner_id=self.user.id,
            name=self.projects.free_name(self.user.id, template.name),
            description=template.description,
            location=template.location,
            status="draft",
        )
        project.terrains = [
            Terrain(
                name="Lote",
                area_m2=template.lot_area_m2,
                width_m=template.lot_width_m,
                length_m=template.lot_length_m,
                slope_percent=template.slope_percent,
                soil_type=template.soil_type,
            )
        ]
        project.plans = [Plan(title=level.title, level=level.level) for level in template.levels]
        project.materials = [
            Material(
                name=material.name,
                category=material.category,
                unit=material.unit,
                quantity=material.quantity,
                unit_cost=material.unit_cost,
            )
            for material in template.materials
        ]
        self.session.add(project)
        self.session.flush()

        for plan, level in zip(project.plans, template.levels, strict=True):
            plan.rooms = [
                Room(
                    project_id=project.id,
                    name=room.name,
                    x_m=room.x_m,
                    y_m=room.y_m,
                    width_m=room.width_m,
                    depth_m=room.depth_m,
                    height_m=level.height_m,
                )
                for room in level.rooms
            ]
            plan.components = [
                StructuralComponent(
                    project_id=project.id,
                    kind="column",
                    name=f"C{number}",
                    x_m=x_m,
                    y_m=y_m,
                    width_m=COLUMN_SIDE_M,
                    depth_m=COLUMN_SIDE_M,
                    height_m=level.height_m,
                )
                for number, (x_m, y_m) in enumerate(corner_columns(level), start=1)
            ]

        self.session.commit()
        self.session.refresh(project)

        return project
