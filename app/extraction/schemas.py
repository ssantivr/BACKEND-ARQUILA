from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_serializer,
    model_validator,
)

from app.extraction.proposal import ProposedField
from app.limits import MAX_TEXT_LENGTH

ExtractionStatus = Literal["review", "applied", "undone", "failed"]


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


class ExtractionAvailability(BaseModel):
    available: bool
    external: bool
    mime_types: list[str]
    max_bytes: int


class ExtractionCreate(BaseModel):
    file_id: int
    consent: StrictBool = False


class Reviewed(BaseModel):
    # Nothing is accepted and then ignored: coordinates and vertices are never filled in by AI.
    model_config = ConfigDict(extra="forbid")


class ReviewedProject(Reviewed):
    description: Annotated[Text, Field(max_length=MAX_TEXT_LENGTH)] | None = None
    location: Annotated[Text, Field(max_length=MAX_TEXT_LENGTH)] | None = None

    @model_validator(mode="after")
    def has_a_value(self) -> "ReviewedProject":
        if self.description is None and self.location is None:
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
