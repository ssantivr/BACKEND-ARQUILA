import json
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.services.geometry import polygon_area

ProjectStatus = Literal["draft", "active", "archived"]
ProjectSort = Literal["id", "name", "created_at", "updated_at", "status", "progress"]
SortOrder = Literal["asc", "desc"]
TaskStatus = Literal["todo", "in_progress", "done"]
Theme = Literal["light", "dark", "auto"]
MeasurementUnits = Literal["metric", "imperial"]
Density = Literal["compact", "comfortable", "spacious"]
PreviewQuality = Literal["low", "medium", "high"]
MAX_JSON_CHARACTERS = 4000
Orientation = Literal["north", "south", "east", "west"]
RecommendationSource = Literal["ai", "user", "system"]
RecommendationPriority = Literal["high", "medium", "low"]
ComponentKind = Literal["column", "beam", "wall"]
ElementKind = Literal["room", "volume", "column", "beam", "wall"]
RoofKind = Literal["gable", "flat"]
SurfaceMaterial = Literal["concrete", "brick", "plaster", "glass", "steel", "wood", "stone"]


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    email: str = Field(max_length=255)


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    created_at: datetime
    display_name: str | None = None
    avatar_file_id: int | None = None


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    avatar_file_id: int | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=255)
    status: ProjectStatus = "draft"


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=255)
    status: ProjectStatus | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    cover_file_id: int | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    description: str | None
    location: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0
    archived_at: datetime | None = None
    cover_file_id: int | None = None


class ProjectPage(BaseModel):
    items: list[ProjectRead]
    total: int
    page: int
    page_size: int


class ProjectDuplicate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)


class TemplateRead(BaseModel):
    id: str
    name: str
    kind: str
    description: str
    levels: int
    lot_area_m2: float
    built_area_m2: float


class TerrainPointData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    x_m: float = Field(ge=-100000, le=100000)
    y_m: float = Field(ge=-100000, le=100000)


def validate_polygon(points: list[TerrainPointData] | None) -> list[TerrainPointData] | None:
    if points is not None and polygon_area([(p.x_m, p.y_m) for p in points]) <= 0:
        raise ValueError("the points must enclose an area greater than zero")

    return points


PolygonPoints = Annotated[
    list[TerrainPointData] | None,
    Field(default=None, min_length=3, max_length=50),
    AfterValidator(validate_polygon),
]


class TerrainCreate(BaseModel):
    points: PolygonPoints
    name: str = Field(min_length=1, max_length=160)
    area_m2: float = Field(gt=0, lt=1e10)
    width_m: float | None = Field(default=None, gt=0, lt=1e6)
    length_m: float | None = Field(default=None, gt=0, lt=1e6)
    slope_percent: float | None = Field(default=None, ge=0, lt=1000)
    soil_type: str | None = Field(default=None, max_length=80)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class TerrainUpdate(BaseModel):
    points: PolygonPoints
    name: str | None = Field(default=None, min_length=1, max_length=160)
    area_m2: float | None = Field(default=None, gt=0, lt=1e10)
    width_m: float | None = Field(default=None, gt=0, lt=1e6)
    length_m: float | None = Field(default=None, gt=0, lt=1e6)
    slope_percent: float | None = Field(default=None, ge=0, lt=1000)
    soil_type: str | None = Field(default=None, max_length=80)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class TerrainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    area_m2: float
    width_m: float | None
    length_m: float | None
    points: list[TerrainPointData]
    slope_percent: float | None
    soil_type: str | None
    latitude: float | None
    longitude: float | None
    created_at: datetime


class MaterialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str | None = Field(default=None, max_length=80)
    unit: str = Field(min_length=1, max_length=20)
    quantity: float = Field(default=0, ge=0, lt=1e10)
    unit_cost: float = Field(default=0, ge=0, lt=1e10)


class MaterialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    category: str | None = Field(default=None, max_length=80)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    quantity: float | None = Field(default=None, ge=0, lt=1e10)
    unit_cost: float | None = Field(default=None, ge=0, lt=1e10)


class MaterialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    category: str | None
    unit: str
    quantity: float
    unit_cost: float
    created_at: datetime


class PlanCreate(BaseModel):
    file_id: int | None = None
    title: str = Field(min_length=1, max_length=160)
    level: str | None = Field(default=None, max_length=60)
    scale: str | None = Field(default=None, max_length=20)


class PlanUpdate(BaseModel):
    file_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    level: str | None = Field(default=None, max_length=60)
    scale: str | None = Field(default=None, max_length=20)


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    file_id: int | None
    title: str
    level: str | None
    scale: str | None
    created_at: datetime


class ElevationCreate(BaseModel):
    file_id: int | None = None
    title: str = Field(min_length=1, max_length=160)
    orientation: Orientation


class ElevationUpdate(BaseModel):
    file_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    orientation: Orientation | None = None


class ElevationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    file_id: int | None
    title: str
    orientation: Orientation
    created_at: datetime


class StructureTerrain(BaseModel):
    id: int
    name: str
    outline: list[TerrainPointData]


class RoomCreate(BaseModel):
    plan_id: int
    name: str = Field(min_length=1, max_length=160)
    x_m: float = Field(ge=-100000, le=100000)
    y_m: float = Field(ge=-100000, le=100000)
    width_m: float = Field(gt=0, lt=1000)
    depth_m: float = Field(gt=0, lt=1000)
    height_m: float = Field(default=3, gt=0, lt=1000)


class RoomUpdate(BaseModel):
    plan_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    x_m: float | None = Field(default=None, ge=-100000, le=100000)
    y_m: float | None = Field(default=None, ge=-100000, le=100000)
    width_m: float | None = Field(default=None, gt=0, lt=1000)
    depth_m: float | None = Field(default=None, gt=0, lt=1000)
    height_m: float | None = Field(default=None, gt=0, lt=1000)


class RoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    plan_id: int
    name: str
    x_m: float
    y_m: float
    width_m: float
    depth_m: float
    height_m: float
    created_at: datetime


class StructureRoom(BaseModel):
    kind: Literal["room", "volume"]
    id: int
    plan_id: int
    plan_title: str
    name: str
    level: str | None
    x_m: float
    y_m: float
    base_m: float
    width_m: float
    depth_m: float
    height_m: float
    surface: SurfaceMaterial | None = None


class ComponentCreate(BaseModel):
    plan_id: int
    kind: ComponentKind
    name: str = Field(min_length=1, max_length=160)
    x_m: float = Field(ge=-100000, le=100000)
    y_m: float = Field(ge=-100000, le=100000)
    width_m: float = Field(gt=0, lt=1000)
    depth_m: float = Field(gt=0, lt=1000)
    height_m: float = Field(gt=0, lt=1000)


class ComponentUpdate(BaseModel):
    plan_id: int | None = None
    kind: ComponentKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    x_m: float | None = Field(default=None, ge=-100000, le=100000)
    y_m: float | None = Field(default=None, ge=-100000, le=100000)
    width_m: float | None = Field(default=None, gt=0, lt=1000)
    depth_m: float | None = Field(default=None, gt=0, lt=1000)
    height_m: float | None = Field(default=None, gt=0, lt=1000)


class ComponentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    plan_id: int
    kind: ComponentKind
    name: str
    x_m: float
    y_m: float
    width_m: float
    depth_m: float
    height_m: float
    created_at: datetime


class StructureComponent(BaseModel):
    kind: ComponentKind
    id: int
    plan_id: int
    plan_title: str
    name: str
    level: str | None
    x_m: float
    y_m: float
    base_m: float
    width_m: float
    depth_m: float
    height_m: float
    surface: SurfaceMaterial | None = None


class SurfaceUpdate(BaseModel):
    surface: SurfaceMaterial


class RoofUpdate(BaseModel):
    roof: RoofKind


class StructureRead(BaseModel):
    project_id: int
    roof: RoofKind
    terrains: list[StructureTerrain]
    rooms: list[StructureRoom]
    components: list[StructureComponent]


class DeletedItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["terrain", "material", "plan", "elevation", "room", "component"]
    label: str


class RecommendationCreate(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=2000)
    priority: RecommendationPriority = "medium"


class RecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    category: str
    content: str
    source: RecommendationSource
    priority: RecommendationPriority
    created_at: datetime


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    filename: str
    mime_type: str
    size_bytes: int
    created_at: datetime


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str | None
    created_at: datetime


class AssistantStatus(BaseModel):
    provider: Literal["ollama", "rules"]
    model: str | None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: Literal["user", "assistant", "system"]
    content: str
    source: Literal["ai", "rules"] | None
    created_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]


class SummaryRead(BaseModel):
    projects: int
    draft_projects: int
    active_projects: int
    archived_projects: int
    terrains: int
    total_area_m2: float
    materials_total_cost: float
    in_progress_projects: int = 0
    completed_projects: int = 0
    materials: int = 0
    plans: int = 0


def within_json_limit[T](value: T) -> T:
    if len(json.dumps(value)) > MAX_JSON_CHARACTERS:
        raise ValueError(f"must take at most {MAX_JSON_CHARACTERS} characters as JSON")

    return value


Coordinate = Annotated[float, Field(ge=-100000, le=100000)]
Vector3 = Annotated[list[Coordinate], Field(min_length=3, max_length=3)]
ShortKey = Annotated[str, Field(min_length=1, max_length=40)]
FlatValue = bool | float | Annotated[str, Field(max_length=200)]


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    user_id: int | None
    action: str
    entity_type: str | None
    entity_id: int | None
    detail: dict[str, Any]
    created_at: datetime


class ActivityPage(BaseModel):
    items: list[ActivityRead]
    total: int
    page: int
    page_size: int


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: TaskStatus = "todo"
    assignee_id: int | None = None
    due_date: date | None = None
    progress: int | None = Field(default=None, ge=0, le=100)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: TaskStatus | None = None
    assignee_id: int | None = None
    due_date: date | None = None
    progress: int | None = Field(default=None, ge=0, le=100)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: str | None
    status: TaskStatus
    assignee_id: int | None
    due_date: date | None
    progress: int
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class VersionCreate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)


class VersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version_number: int
    label: str | None
    created_by: int | None
    created_at: datetime
    contents: dict[str, int]


class VersionDetail(VersionRead):
    snapshot: dict[str, Any]


class PreferencesUpdate(BaseModel):
    theme: Theme | None = None
    units: MeasurementUnits | None = None
    density: Density | None = None
    reduce_motion: bool | None = None
    preview_quality: PreviewQuality | None = None
    camera_defaults: Annotated[dict[ShortKey, Any] | None, AfterValidator(within_json_limit)] = None
    notifications: Annotated[dict[ShortKey, bool] | None, Field(max_length=30)] = None


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: Theme
    units: MeasurementUnits
    density: Density
    reduce_motion: bool
    preview_quality: PreviewQuality
    camera_defaults: dict[str, Any]
    notifications: dict[str, bool]


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationsMarked(BaseModel):
    updated: int


class CameraPreset(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    position: Vector3
    target: Vector3
    fov: float | None = Field(default=None, ge=10, le=120)


class SceneSettingsUpdate(BaseModel):
    lighting: Annotated[dict[ShortKey, FlatValue] | None, Field(max_length=30)] = None
    camera_presets: Annotated[list[CameraPreset] | None, Field(max_length=20)] = None


class SceneSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    lighting: dict[str, Any]
    camera_presets: list[CameraPreset]
    updated_at: datetime | None


class WalkthroughPointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    position: Vector3
    target: Vector3
    sort_order: int = Field(default=0, ge=0, le=100000)


class WalkthroughPointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    position: Vector3 | None = None
    target: Vector3 | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)


class WalkthroughPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    position: list[float]
    target: list[float]
    sort_order: int
    created_at: datetime
    updated_at: datetime
