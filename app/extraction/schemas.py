from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    field_serializer,
    model_validator,
)

from app.extraction.proposal import ProposedField
from app.limits import MAX_TEXT_LENGTH
from app.schemas import ComponentKind

ExtractionStatus = Literal["review", "applied", "undone", "failed"]
BuildOrigin = Literal["description", "document"]

MAX_LEVELS = 10
MAX_ROOMS = 50
MAX_COMPONENTS = 100
# Read once and never stored, with the limit of every text a user types (R07).
MAX_DESCRIPTION_LENGTH = MAX_TEXT_LENGTH
MAX_BUILD_DESCRIPTION_LENGTH = 2_000


def without_nul(text: str) -> str:
    if "\x00" in text:
        raise ValueError("the text has a character that cannot be stored")

    return text


Text = Annotated[str, Field(min_length=1), AfterValidator(without_nul)]


def two_decimals(value: float) -> float:
    rounded = round(value, 2)

    if rounded <= 0:
        raise ValueError("the value is too small")

    return rounded


def rounded_first(value: object) -> object:
    """The columns keep two decimals: the bounds are checked on the value that is stored."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return round(value, 2)

    return value


class ExtractionAvailability(BaseModel):
    available: bool
    external: bool
    mime_types: list[str]
    max_bytes: int


class ExtractionCreate(BaseModel):
    file_id: int
    consent: StrictBool = False


class Reviewed(BaseModel):
    # Reject fields a workflow does not explicitly support.
    model_config = ConfigDict(extra="forbid")


class ReviewedProject(Reviewed):
    name: Annotated[Text, Field(max_length=160)] | None = None
    description: Annotated[Text, Field(max_length=MAX_TEXT_LENGTH)] | None = None
    location: Annotated[Text, Field(max_length=MAX_TEXT_LENGTH)] | None = None

    @model_validator(mode="after")
    def has_a_value(self) -> "ReviewedProject":
        if self.name is None and self.description is None and self.location is None:
            raise ValueError("there is nothing to apply")

        return self


class ReviewedTerrain(Reviewed):
    name: Annotated[Text, Field(max_length=160)]
    area_m2: Annotated[float, Field(gt=0, le=9_999_999_999), AfterValidator(two_decimals)]
    width_m: Annotated[float, Field(gt=0, le=999_999.99), AfterValidator(two_decimals)] | None = (
        None
    )
    length_m: Annotated[float, Field(gt=0, le=999_999.99), AfterValidator(two_decimals)] | None = (
        None
    )
    slope_percent: float | None = Field(default=None, ge=0, le=999.99)
    soil_type: Annotated[Text, Field(max_length=80)] | None = None


class ReviewedPlan(Reviewed):
    title: Annotated[Text, Field(max_length=160)]
    level: Annotated[Text, Field(max_length=60)] | None = None
    scale: Annotated[Text, Field(max_length=20)] | None = None


class ExtractionApply(Reviewed):
    """What the user kept after reviewing the proposal."""

    project: ReviewedProject | None = None
    terrain: ReviewedTerrain | None = None
    plan: ReviewedPlan | None = None

    @model_validator(mode="after")
    def has_something(self) -> "ExtractionApply":
        if self.project is None and self.terrain is None and self.plan is None:
            raise ValueError("there is nothing to apply")

        return self


class ExtractionRead(BaseModel):
    id: int
    project_id: int
    file_id: int | None
    status: ExtractionStatus
    proposal: dict[str, dict[str, ProposedField]]
    terrain_id: int | None
    plan_id: int | None
    project_fields: list[str]
    created_at: datetime

    @field_serializer("created_at")
    def in_utc(self, value: datetime) -> str:
        # Stored in UTC without an offset: a browser would read it as local time (R18).
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

        return aware.isoformat().replace("+00:00", "Z")


Name = Annotated[Text, Field(max_length=160)]
Measure = Annotated[float, BeforeValidator(rounded_first), Field(gt=0, lt=1000)]
Position = Annotated[float, BeforeValidator(rounded_first), Field(ge=-100_000, le=100_000)]
Fields = dict[str, ProposedField]


class BuildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Annotated[Text, Field(max_length=MAX_BUILD_DESCRIPTION_LENGTH)] | None = None
    file_id: int | None = None
    consent: StrictBool = False

    @model_validator(mode="after")
    def has_one_source(self) -> "BuildCreate":
        if self.description is None and self.file_id is None:
            raise ValueError("give a description, a document, or both")

        return self


class BuildRoom(Reviewed):
    """Coordinates are completed deterministically and reviewed by the user."""

    name: Name
    x_m: Position
    y_m: Position
    width_m: Measure
    depth_m: Measure
    height_m: Measure


class BuildComponent(BuildRoom):
    kind: ComponentKind


class BuildLevel(Reviewed):
    title: Name
    level: Annotated[Text, Field(max_length=60)] | None = None
    scale: Annotated[Text, Field(max_length=20)] | None = None
    rooms: list[BuildRoom] = Field(default_factory=list, max_length=MAX_ROOMS)
    components: list[BuildComponent] = Field(default_factory=list, max_length=MAX_COMPONENTS)


class BuildRecommendation(BaseModel):
    category: Annotated[Text, Field(max_length=80)]
    content: Annotated[Text, Field(max_length=MAX_TEXT_LENGTH)]
    priority: Literal["high", "medium", "low"] = "medium"


class BuildApply(Reviewed):
    """What the user confirmed after reviewing and completing the proposal."""

    levels: list[BuildLevel] = Field(min_length=1, max_length=MAX_LEVELS)
    project: ReviewedProject | None = None
    terrain: ReviewedTerrain | None = None


class ProposedLevel(BaseModel):
    fields: Fields = Field(default_factory=dict)
    rooms: list[Fields] = Field(default_factory=list)
    components: list[Fields] = Field(default_factory=list)


class BuildProposal(BaseModel):
    origin: BuildOrigin
    fallback: bool = False
    levels: list[ProposedLevel] = Field(default_factory=list)
    project: Fields = Field(default_factory=dict)
    terrain: Fields = Field(default_factory=dict)
    recommendations: list[BuildRecommendation] = Field(default_factory=list, max_length=20)
    # More levels, rooms or components than the limits were proposed: the rest was left out.
    truncated: bool = False


class BuildRead(BaseModel):
    id: int
    project_id: int
    file_id: int | None
    status: ExtractionStatus
    origin: BuildOrigin
    fallback: bool
    levels: list[ProposedLevel]
    project: Fields = Field(default_factory=dict)
    terrain: Fields = Field(default_factory=dict)
    recommendations: list[BuildRecommendation] = Field(default_factory=list, max_length=20)
    truncated: bool
    plan_ids: list[int]
    created_at: datetime

    @field_serializer("created_at")
    def in_utc(self, value: datetime) -> str:
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

        return aware.isoformat().replace("+00:00", "Z")
