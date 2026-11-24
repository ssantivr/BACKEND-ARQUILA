import json
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.limits import MAX_TEXT_LENGTH

Layer = Literal["structure", "installations", "finishes"]
WorkStatus = Literal["existing", "planned", "demolition"]
PropertyType = Literal["house", "apartment_building", "commercial", "mixed_use"]
PropertyStatus = Literal["planning", "under_construction", "renovation", "delivered"]
UnitStatus = Literal["available", "reserved", "sold", "under_renovation"]
RenovationStatus = Literal["planned", "in_progress", "completed", "cancelled"]
RoleName = Literal["admin", "architect", "viewer"]
RoomCategory = Literal[
    "master_bedroom",
    "bedroom",
    "living_dining",
    "kitchen",
    "bathroom",
    "study",
    "circulation",
    "service",
    "garage",
    "commercial",
    "other",
]

MAX_CONFIG_BYTES = 20_000
COORDINATE_LIMIT_M = 100_000


def limit_config_size(config: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(config).encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ValueError(f"La configuración no puede superar {MAX_CONFIG_BYTES // 1000} kB.")

    return config


def is_point(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(item, int | float) and not isinstance(item, bool) for item in value)
    )


def check_camera(config: dict[str, Any]) -> dict[str, Any]:
    camera = config.get("camera")

    if camera is not None and not (
        isinstance(camera, dict)
        and is_point(camera.get("position"))
        and is_point(camera.get("target"))
    ):
        raise ValueError(
            "La cámara debe tener «position» y «target» como listas de tres números [x, y, z]."
        )

    return config


JsonConfig = Annotated[dict[str, Any], AfterValidator(limit_config_size)]
ViewConfig = Annotated[JsonConfig, AfterValidator(check_camera)]
SceneFormat = Literal["json", "gltf"]
Coordinate = Annotated[float, Field(ge=-COORDINATE_LIMIT_M, le=COORDINATE_LIMIT_M)]
Name = Annotated[str, Field(min_length=1, max_length=160)]
AssetRef = Annotated[str, Field(min_length=1, max_length=500)]


class AccessTokenRead(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class AccessRead(BaseModel):
    id: int
    name: str
    email: str
    roles: list[str]
    permissions: list[str]


class RoleAssignment(BaseModel):
    roles: list[RoleName] = Field(min_length=1)


class PropertyCreate(BaseModel):
    project_id: int
    name: Name
    property_type: PropertyType = "house"
    address: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    status: PropertyStatus = "planning"
    spatial_metadata: JsonConfig = Field(default_factory=dict)


class PropertyUpdate(BaseModel):
    name: Name | None = None
    property_type: PropertyType | None = None
    address: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    status: PropertyStatus | None = None
    spatial_metadata: JsonConfig | None = None


class PropertyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    property_type: PropertyType
    address: str | None
    status: PropertyStatus
    spatial_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class UnitCreate(BaseModel):
    property_id: int
    code: str = Field(min_length=1, max_length=40)
    name: Name
    floor_level: int = Field(default=0, ge=-10, le=200)
    status: UnitStatus = "available"
    price: float | None = Field(default=None, ge=0, lt=1e12)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    area_m2: float | None = Field(default=None, gt=0, lt=1e8)
    model_asset_ref: AssetRef | None = None
    asset_config: JsonConfig = Field(default_factory=dict)


class UnitUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: Name | None = None
    floor_level: int | None = Field(default=None, ge=-10, le=200)
    status: UnitStatus | None = None
    price: float | None = Field(default=None, ge=0, lt=1e12)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    area_m2: float | None = Field(default=None, gt=0, lt=1e8)
    model_asset_ref: AssetRef | None = None
    asset_config: JsonConfig | None = None


class UnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    property_id: int
    code: str
    name: str
    floor_level: int
    status: UnitStatus
    price: float | None
    currency: str
    area_m2: float | None
    model_asset_ref: str | None
    asset_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RoomSpatialUpdate(BaseModel):
    unit_id: int | None = None
    category: RoomCategory | None = None
    mesh_ref: AssetRef | None = None


class RoomSpatialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    plan_id: int
    unit_id: int | None
    name: str
    category: RoomCategory
    mesh_ref: str | None
    x_m: float
    y_m: float
    width_m: float
    depth_m: float
    height_m: float


class SpatialElementCreate(BaseModel):
    project_id: int
    room_id: int | None = None
    layer: Layer
    kind: str = Field(pattern="^[a-z][a-z0-9_]{0,39}$")
    name: Name
    work_status: WorkStatus = "existing"
    min_x_m: Coordinate
    min_y_m: Coordinate
    min_z_m: Coordinate
    max_x_m: Coordinate
    max_y_m: Coordinate
    max_z_m: Coordinate
    mesh_ref: AssetRef | None = None
    config: JsonConfig = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        for axis in ("x", "y", "z"):
            if getattr(self, f"max_{axis}_m") <= getattr(self, f"min_{axis}_m"):
                raise ValueError(f"max_{axis}_m debe ser mayor que min_{axis}_m.")

        return self


class SpatialElementUpdate(BaseModel):
    room_id: int | None = None
    layer: Layer | None = None
    kind: str | None = Field(default=None, pattern="^[a-z][a-z0-9_]{0,39}$")
    name: Name | None = None
    work_status: WorkStatus | None = None
    min_x_m: Coordinate | None = None
    min_y_m: Coordinate | None = None
    min_z_m: Coordinate | None = None
    max_x_m: Coordinate | None = None
    max_y_m: Coordinate | None = None
    max_z_m: Coordinate | None = None
    mesh_ref: AssetRef | None = None
    config: JsonConfig | None = None


class SpatialElementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    room_id: int | None
    layer: Layer
    kind: str
    name: str
    work_status: WorkStatus
    min_x_m: float
    min_y_m: float
    min_z_m: float
    max_x_m: float
    max_y_m: float
    max_z_m: float
    mesh_ref: str | None
    config: dict[str, Any]
    source: str
    external_id: str | None
    created_at: datetime


class SpatialDataRead(BaseModel):
    project_id: int
    counts: dict[Layer, int]
    elements: list[SpatialElementRead]


class SpatialImportRequest(BaseModel):
    project_id: int
    provider: str = Field(min_length=1, max_length=20)
    document: dict[str, Any]
    layer: Layer = "installations"
    work_status: WorkStatus = "existing"


class SpatialImportRead(BaseModel):
    provider: str
    created: int
    updated: int
    elements: list[SpatialElementRead]


class WalkthroughStepCreate(BaseModel):
    project_id: int
    room_id: int | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    title: Name
    description: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    duration_ms: int = Field(default=5000, ge=1000, le=60_000)
    view_config: ViewConfig = Field(default_factory=dict)


class WalkthroughStepUpdate(BaseModel):
    room_id: int | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    title: Name | None = None
    description: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    duration_ms: int | None = Field(default=None, ge=1000, le=60_000)
    view_config: ViewConfig | None = None


class WalkthroughStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    room_id: int | None
    position: int
    title: str
    description: str | None
    duration_ms: int
    view_config: dict[str, Any]
    created_at: datetime


def check_timeline(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio.")


class RenovationLogCreate(BaseModel):
    project_id: int
    room_id: int | None = None
    spatial_element_id: int | None = None
    layer: Layer
    title: Name
    description: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    status: RenovationStatus = "planned"
    planned_start: date | None = None
    planned_end: date | None = None
    estimated_cost: float | None = Field(default=None, ge=0, lt=1e10)

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        check_timeline(self.planned_start, self.planned_end)

        return self


class RenovationLogUpdate(BaseModel):
    room_id: int | None = None
    spatial_element_id: int | None = None
    layer: Layer | None = None
    title: Name | None = None
    description: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    status: RenovationStatus | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    estimated_cost: float | None = Field(default=None, ge=0, lt=1e10)


class RenovationLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    room_id: int | None
    spatial_element_id: int | None
    created_by: int | None
    layer: Layer
    title: str
    description: str | None
    status: RenovationStatus
    planned_start: date | None
    planned_end: date | None
    completed_at: datetime | None
    estimated_cost: float | None
    created_at: datetime
    updated_at: datetime


class WalkthroughRead(BaseModel):
    project_id: int
    steps: list[WalkthroughStepRead]
    renovation_logs: list[RenovationLogRead]
