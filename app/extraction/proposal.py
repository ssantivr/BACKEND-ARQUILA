"""What a provider may propose from a document. Anything else it answers is dropped."""

import json
import math
import unicodedata
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.extraction.evidence import holds_coordinates, is_supported
from app.limits import MAX_TEXT_LENGTH
from app.schemas import PlanCreate, ProjectCreate, TerrainCreate

SECTIONS: dict[str, tuple[type[BaseModel], tuple[str, ...], tuple[str, ...]]] = {
    "project": (ProjectCreate, ("description", "location"), ()),
    "terrain": (
        TerrainCreate,
        ("name", "area_m2", "width_m", "length_m", "slope_percent", "soil_type"),
        ("name", "area_m2"),
    ),
    "plan": (PlanCreate, ("title", "level", "scale"), ("title",)),
}

# D-AI-3 is still open: until the owner decides, only very sure answers are applied on their own.
AUTO_APPLY_CONFIDENCE = 0.85
MAX_ANSWER_CHARS = 100_000


class ProposedField(BaseModel):
    value: str | float
    confidence: float = Field(ge=0, le=1)
    source: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)


Proposal = dict[str, dict[str, ProposedField]]


@dataclass(frozen=True)
class Reading:
    proposal: Proposal
    # False when something was rejected, is missing, is doubtful or has no quote to support it.
    sure: bool


def is_storable(text: str) -> bool:
    # PostgreSQL refuses NUL and lone surrogates.
    return not any(
        unicodedata.category(char) in ("Cc", "Cs") and char not in "\n\r\t" for char in text
    )


def _is_valid(schema: type[BaseModel], name: str, value: str | float) -> bool:
    field = schema.model_fields[name]

    try:
        TypeAdapter(field.rebuild_annotation()).validate_python(value, strict=True)
    except ValidationError:
        return False

    return True


def clean_value(schema: type[BaseModel], name: str, value: Any) -> str | float | None:
    if isinstance(value, str):
        value = value.strip()

        if not value or not is_storable(value):
            return None

        if name in ("description", "location") and holds_coordinates(value):
            return None
    elif isinstance(value, int | float) and not isinstance(value, bool):
        try:
            number = float(value)
        except OverflowError:
            return None

        if not math.isfinite(number):
            return None

        # The columns keep two decimals: the rounded value is the one that has to be valid.
        value = round(number, 2)
    else:
        return None

    return value if _is_valid(schema, name, value) else None


def _read_field(
    schema: type[BaseModel], name: str, answer: Any
) -> tuple[ProposedField | None, bool]:
    """The field, and whether it is sure enough to be applied without review."""
    if not isinstance(answer, dict):
        return None, False

    source = answer.get("source")

    # A value without the place it was read from could be invented: it stays empty.
    if not isinstance(source, str) or not source.strip() or not is_storable(source):
        return None, False

    value = clean_value(schema, name, answer.get("value"))

    if value is None:
        return None, False

    given = answer.get("confidence")
    confidence = 0.0

    if not isinstance(given, bool) and isinstance(given, int | float) and 0 <= given <= 1:
        confidence = float(given)

    sure = confidence >= AUTO_APPLY_CONFIDENCE and is_supported(name, value, source)
    field = ProposedField(
        value=value, confidence=confidence, source=source.strip()[:MAX_TEXT_LENGTH].strip()
    )

    return field, sure


def read_proposal(answer: str) -> Reading:
    """The valid fields of a provider's JSON answer. Raises ValueError when it is unusable."""
    if len(answer) > MAX_ANSWER_CHARS:
        raise ValueError("The answer is too long")

    try:
        data = json.loads(answer)
    except RecursionError:
        raise ValueError("The answer is nested too deeply") from None

    if not isinstance(data, dict):
        raise ValueError("The answer is not a JSON object")

    proposal: Proposal = {}
    sure = True

    for section, (schema, names, required) in SECTIONS.items():
        answers = data.get(section)

        if answers is None or answers == {}:
            continue

        if not isinstance(answers, dict):
            sure = False
            continue

        fields: dict[str, ProposedField] = {}

        for name in names:
            given = answers.get(name)

            if given is None or (isinstance(given, dict) and given.get("value") is None):
                continue

            field, field_sure = _read_field(schema, name, given)
            sure = sure and field_sure

            if field is not None:
                fields[name] = field

        if any(name not in fields for name in required):
            sure = False

        if fields:
            proposal[section] = fields
        else:
            sure = False

    return Reading(proposal, sure and bool(proposal))
