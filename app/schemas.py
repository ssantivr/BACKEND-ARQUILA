from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.limits import MAX_EMAIL_LENGTH, MAX_TEXT_LENGTH
from app.services.geometry import polygon_area

ProjectStatus = Literal["draft", "active", "archived"]
Orientation = Literal["north", "south", "east", "west"]
RecommendationSource = Literal["ai", "user", "system"]
RecommendationPriority = Literal["high", "medium", "low"]
ComponentKind = Literal["column", "beam", "wall"]
ElementKind = Literal["room", "volume", "column", "beam", "wall"]
RoofKind = Literal["gable", "flat"]
SurfaceMaterial = Literal["concrete", "brick", "plaster", "glass", "steel", "wood", "stone"]


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=MAX_EMAIL_LENGTH, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    password: str = Field(max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    created_at: datetime


Latitude = Annotated[float | None, Field(ge=-90, le=90)]
Longitude = Annotated[float | None, Field(ge=-180, le=180)]
MapZoom = Annotated[int | None, Field(ge=1, le=19)]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    location: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    status: ProjectStatus = "draft"
    latitude: Latitude = None
    longitude: Longitude = None
    location_zoom: MapZoom = None

    @model_validator(mode="after")
    def coordinates_come_together(self) -> "ProjectCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude go together")

        return self


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    # Wider than 200 on purpose: ProjectService limits only a text that changes.
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=255)
    status: ProjectStatus | None = None
    latitude: Latitude = None
    longitude: Longitude = None
    location_zoom: MapZoom = None

    @model_validator(mode="after")
    def coordinates_come_together(self) -> "ProjectUpdate":
        sent = self.model_fields_set & {"latitude", "longitude"}

        if len(sent) == 1 or (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude go together")

        return self


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    description: str | None
    location: str | None
    latitude: float | None
    longitude: float | None
    location_zoom: int | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


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
    content: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
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
