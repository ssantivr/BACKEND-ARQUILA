from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Plan, Project, Room, StructuralComponent, Terrain, User
from app.repositories.component_repository import ComponentRepository
from app.repositories.plan_repository import PlanRepository
from app.repositories.room_repository import RoomRepository
from app.repositories.terrain_repository import TerrainRepository
from app.schemas import (
    StructureComponent,
    StructureRead,
    StructureRoom,
    StructureTerrain,
    TerrainPointData,
)
from app.services.base import ProjectScopedService

STOREY_HEIGHT_M = 3.0
DEFAULT_SETBACK_M = 3.0
TERRAIN_GAP_M = 5.0

Outline = list[tuple[float, float]]
Lot = tuple[float, float, float]


def terrain_outline(terrain: Terrain) -> Outline | None:
    if len(terrain.points) >= 3:
        return [(float(point.x_m), float(point.y_m)) for point in terrain.points]

    if terrain.width_m is not None and terrain.length_m is not None:
        width, length = float(terrain.width_m), float(terrain.length_m)
        return [(0.0, 0.0), (width, 0.0), (width, length), (0.0, length)]

    return None


def is_rectangular(terrain: Terrain) -> bool:
    return len(terrain.points) < 3


def setback_for(width: float, length: float) -> float:
    return min(DEFAULT_SETBACK_M, min(width, length) / 4)


def has_numeric_level(plan: Plan) -> bool:
    try:
        float(plan.level or "")
    except ValueError:
        return False

    return True


def build_volume(plan: Plan, lot: Lot, base: float) -> StructureRoom:
    origin_x, width, length = lot
    setback = setback_for(width, length)

    return StructureRoom(
        kind="volume",
        id=plan.id,
        plan_id=plan.id,
        plan_title=plan.title,
        name=plan.title,
        level=plan.level,
        x_m=origin_x + width / 2,
        y_m=length / 2,
        base_m=base,
        width_m=width - 2 * setback,
        depth_m=length - 2 * setback,
        height_m=STOREY_HEIGHT_M,
        surface=plan.surface,
    )


def build_room(plan: Plan, room: Room, base: float) -> StructureRoom:
    width, depth = float(room.width_m), float(room.depth_m)

    return StructureRoom(
        kind="room",
        id=room.id,
        plan_id=plan.id,
        plan_title=plan.title,
        name=room.name,
        level=plan.level,
        x_m=float(room.x_m) + width / 2,
        y_m=float(room.y_m) + depth / 2,
        base_m=base,
        width_m=width,
        depth_m=depth,
        height_m=float(room.height_m),
        surface=room.surface,
    )


def build_component(
    plan: Plan, component: StructuralComponent, base: float, level_height: float
) -> StructureComponent:
    width, depth, height = (
        float(component.width_m),
        float(component.depth_m),
        float(component.height_m),
    )
    hangs = component.kind == "beam"

    return StructureComponent(
        kind=component.kind,
        id=component.id,
        plan_id=plan.id,
        plan_title=plan.title,
        name=component.name,
        level=plan.level,
        x_m=float(component.x_m) + width / 2,
        y_m=float(component.y_m) + depth / 2,
        base_m=base + max(level_height - height, 0) if hangs else base,
        width_m=width,
        depth_m=depth,
        height_m=height,
        surface=component.surface,
    )


def level_height(rooms: list[Room], components: list[StructuralComponent]) -> float:
    heights = [float(room.height_m) for room in rooms] + [
        float(component.height_m) for component in components if component.kind != "beam"
    ]

    return max(heights, default=STOREY_HEIGHT_M)


def group_by_plan(items: list) -> dict[int, list]:
    grouped: dict[int, list] = {}

    for item in items:
        grouped.setdefault(item.plan_id, []).append(item)

    return grouped


class StructureService(ProjectScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.terrains = TerrainRepository(session)
        self.plans = PlanRepository(session)
        self.rooms = RoomRepository(session)
        self.components = ComponentRepository(session)

    def build(self, project_id: int) -> StructureRead:
        project = self._project(project_id)

        terrains, lot = self._place_terrains(project_id)
        rooms, components = self._stack_levels(project_id, lot)

        return StructureRead(
            project_id=project_id,
            roof=project.roof,
            terrains=terrains,
            rooms=rooms,
            components=components,
        )

    def set_roof(self, project_id: int, roof: str) -> None:
        project = self._project(project_id)

        if project.roof != roof:
            self._record(
                "updated",
                "project",
                project.id,
                project.id,
                project.name,
                fields=["roof"],
                old_value={"roof": project.roof},
                new_value={"roof": roof},
            )

        project.roof = roof
        self.projects.save(project)

    def set_surface(self, project_id: int, kind: str, element_id: int, surface: str) -> None:
        self._ensure_project_exists(project_id)

        if kind == "room":
            repository, element = self.rooms, self.rooms.get(element_id)
        elif kind == "volume":
            repository, element = self.plans, self.plans.get(element_id)
        else:
            repository, element = self.components, self.components.get(element_id)

            if element is not None and element.kind != kind:
                element = None

        if element is None or element.project_id != project_id:
            raise NotFoundError("Element not found")

        if element.surface != surface:
            entity = {"room": "room", "volume": "plan"}.get(kind, "component")
            self._record(
                "updated",
                entity,
                project_id,
                element.id,
                getattr(element, "name", None) or element.title,
                fields=["surface"],
                old_value={"surface": element.surface},
                new_value={"surface": surface},
            )

        element.surface = surface
        repository.save(element)

    def _project(self, project_id: int) -> Project:
        project = self.projects.get_owned(project_id, self.user.id)

        if project is None:
            raise NotFoundError("Project not found")

        return project

    def _place_terrains(self, project_id: int) -> tuple[list[StructureTerrain], Lot | None]:
        placed: list[StructureTerrain] = []
        lot: Lot | None = None
        cursor_x = 0.0

        for terrain in self.terrains.list_by_project(project_id):
            outline = terrain_outline(terrain)

            if outline is None:
                continue

            min_x = min(x for x, _ in outline)
            min_y = min(y for _, y in outline)
            width = max(x for x, _ in outline) - min_x
            length = max(y for _, y in outline) - min_y

            placed.append(
                StructureTerrain(
                    id=terrain.id,
                    name=terrain.name,
                    outline=[
                        TerrainPointData(x_m=x - min_x + cursor_x, y_m=y - min_y)
                        for x, y in outline
                    ],
                )
            )

            if lot is None and is_rectangular(terrain):
                lot = (cursor_x, width, length)

            cursor_x += width + TERRAIN_GAP_M

        return placed, lot

    def _stack_levels(
        self, project_id: int, lot: Lot | None
    ) -> tuple[list[StructureRoom], list[StructureComponent]]:
        rooms_by_plan = group_by_plan(self.rooms.list_by_project(project_id))
        components_by_plan = group_by_plan(self.components.list_by_project(project_id))

        rooms: list[StructureRoom] = []
        components: list[StructureComponent] = []
        modelled = bool(rooms_by_plan or components_by_plan)
        base = 0.0

        for plan in self.plans.list_by_project(project_id):
            own_rooms = rooms_by_plan.get(plan.id, [])
            own_components = components_by_plan.get(plan.id, [])

            if not own_rooms and not own_components and not has_numeric_level(plan):
                continue

            height = level_height(own_rooms, own_components)
            rooms.extend(build_room(plan, room, base) for room in own_rooms)
            components.extend(
                build_component(plan, component, base, height) for component in own_components
            )

            if not modelled and lot is not None:
                rooms.append(build_volume(plan, lot, base))

            base += height

        return rooms, components
