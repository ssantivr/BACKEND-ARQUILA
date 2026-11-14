from contextvars import ContextVar
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models import ActivityEntry, User
from app.repositories.activity_repository import ActivityRepository

Origin = Literal["user", "ai", "system"]

MODULE_HEADER = "X-Arquila-Module"
# The modules of a project as the frontend names them. A header with any other value is
# ignored, so the column only ever holds one of these.
SOURCE_MODULES = frozenset(
    {
        "home",
        "projects",
        "settings",
        "summary",
        "viewer",
        "terrain",
        "plans",
        "elevations",
        "lighting",
        "analysis",
        "files",
        "versions",
        "materials",
        "compare",
        "tasks",
        "render",
        "history",
        "assistant",
    }
)

# Set once per request from MODULE_HEADER (see app.main), read by every entry it records.
current_module: ContextVar[str | None] = ContextVar("current_module", default=None)


def module_from_header(value: str | None) -> str | None:
    module = (value or "").strip().lower()

    return module if module in SOURCE_MODULES else None


def json_safe(value: Any) -> Any:
    """A value the JSON column can store as it is."""
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime | date):
        return value.isoformat()

    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}

    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]

    return value


def as_stored(current: Any, value: Any) -> Any:
    """`value` as the column will keep it. Numeric columns come back as Decimal with their scale,
    while the API sends floats: 1.1 is stored as Decimal("1.10"), and 4.567 as Decimal("4.57")."""
    if (
        isinstance(current, Decimal)
        and isinstance(value, int | float)
        and not isinstance(value, bool)
    ):
        return Decimal(str(value)).quantize(current, rounding=ROUND_HALF_EVEN)

    return value


def field_changes(entity: object, changes: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The fields of `changes` whose stored value would differ from the entity, before and after.

    Call it before applying the changes to the entity. A field sent with the value it already has,
    such as 1.1 for a column holding 1.10, is not a change.
    """
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    for field, value in changes.items():
        current = getattr(entity, field, None)
        stored = as_stored(current, value)

        if current != stored:
            before[field] = json_safe(current)
            after[field] = json_safe(stored)

    return before, after


def record_activity(
    session: Session,
    user: User,
    project_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    *,
    origin: Origin = "user",
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    **detail: Any,
) -> None:
    ActivityRepository(session).add(
        ActivityEntry(
            project_id=project_id,
            user_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=json_safe(detail),
            origin=origin,
            source_module=current_module.get(),
            old_value=json_safe(old_value) if old_value else None,
            new_value=json_safe(new_value) if new_value else None,
        )
    )
