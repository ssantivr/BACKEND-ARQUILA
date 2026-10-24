"""Copy of the design of a project as a JSON document, and the way back.

The document holds the editable contents of the project (terrains with their
vertices, materials, elevations, plans with their rooms and components, tasks,
walkthrough points and scene settings) and a few project fields. Files are not
copied: they are only referenced, and a reference to a file that no longer
belongs to the project is dropped when the document is applied.
"""

import math
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import BigInteger, Column, Numeric, SmallInteger, select, update
from sqlalchemy.orm import Session

from app.database import Base
from app.errors import InvalidDataError
from app.models import (
    Elevation,
    File,
    Material,
    Plan,
    Project,
    Property,
    RenovationLog,
    Room,
    SceneSettings,
    SpatialElement,
    StructuralComponent,
    Task,
    Terrain,
    TerrainPoint,
    Unit,
    WalkthroughPoint,
    WalkthroughStep,
)
from app.services.undo_history import column_values, decode_values, encode_values

SNAPSHOT_FORMAT = 1
PROJECT_FIELDS = ("description", "location", "roof", "progress", "cover_file_id")
FLAT_COLLECTIONS: dict[str, type[Base]] = {
    "materials": Material,
    "elevations": Elevation,
    "tasks": Task,
    "walkthrough_points": WalkthroughPoint,
}


# Links to the parent rows: the new rows get them from where they are placed.
PARENT_COLUMNS = ("project_id", "plan_id", "terrain_id")
UNREADABLE = "This version is not in a format the server can read"
WRONG_VALUE = "This version holds a value that does not fit its field"


def values_of(instance: Base) -> dict[str, Any]:
    values = column_values(instance, instance.__table__)

    for name in PARENT_COLUMNS:
        values.pop(name, None)

    return encode_values(values)


def in_order(instances: Iterable[Base]) -> list[Base]:
    return sorted(instances, key=lambda instance: instance.id)


def take(project: Project) -> dict[str, Any]:
    terrains = [
        {
            **values_of(terrain),
            "points": [values_of(point) for point in terrain.points],
        }
        for terrain in in_order(project.terrains)
    ]
    plans = [
        {
            **values_of(plan),
            "rooms": [values_of(room) for room in in_order(plan.rooms)],
            "components": [values_of(component) for component in in_order(plan.components)],
        }
        for plan in in_order(project.plans)
    ]

    return {
        "format": SNAPSHOT_FORMAT,
        "project": encode_values({field: getattr(project, field) for field in PROJECT_FIELDS}),
        "terrains": terrains,
        "plans": plans,
        **{
            name: [values_of(item) for item in in_order(getattr(project, name))]
            for name in FLAT_COLLECTIONS
        },
        "scene_settings": None
        if project.scene_settings is None
        else values_of(project.scene_settings),
    }


def parses(python_type: type[date], value: str) -> bool:
    try:
        python_type.fromisoformat(value)
    except ValueError:
        return False

    return True


def integer_limit(column_type: Any) -> int:
    # The sizes of PostgreSQL; SQLite would take any integer and only PostgreSQL would refuse it.
    if isinstance(column_type, SmallInteger):
        return 2**15

    if isinstance(column_type, BigInteger):
        return 2**63

    return 2**31


def fits_numeric(column_type: Numeric, value: Any) -> bool:
    if isinstance(value, (int, float)):
        value = str(value)

    if not isinstance(value, str):
        return False

    try:
        number = Decimal(value)
    except InvalidOperation:
        return False

    if not number.is_finite():
        return False

    if column_type.precision is None:
        return True

    # More digits left of the point would overflow the column in PostgreSQL; SQLite takes them.
    return abs(number) < Decimal(10) ** (column_type.precision - (column_type.scale or 0))


def fits(column: Column, value: Any) -> bool:
    """Whether a value of a snapshot can be written to its column, the way decode_values reads it.

    Checked here rather than left to the database, so that SQLite, which takes almost anything,
    and PostgreSQL answer the same.
    """
    if value is None:
        return bool(column.nullable)

    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return True

    if python_type is bool:
        return isinstance(value, bool)

    # True and False are ints in Python, but they are not numbers of a project.
    if isinstance(value, bool):
        return False

    if python_type is int:
        limit = integer_limit(column.type)
        return isinstance(value, int) and -limit <= value < limit

    if python_type is float:
        return isinstance(value, (int, float)) and math.isfinite(value)

    if python_type is Decimal:
        return fits_numeric(column.type, value)

    if python_type is str:
        length = getattr(column.type, "length", None)
        return isinstance(value, str) and (length is None or len(value) <= length)

    if python_type in (datetime, date):
        return isinstance(value, str) and parses(python_type, value)

    if python_type in (dict, list):
        return isinstance(value, (dict, list))

    return True


def check_rows(rows: Any, model: type[Base], nested: tuple[str, ...] = ()) -> list[dict]:
    # take() writes neither ids nor links to the parent, and a key that the model does not have
    # would only fail later, when the row is built.
    allowed = {column.name for column in model.__table__.columns} - {"id", *PARENT_COLUMNS}
    allowed |= set(nested)

    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise InvalidDataError(UNREADABLE)

    if any(set(row) - allowed for row in rows):
        raise InvalidDataError(UNREADABLE)

    columns = model.__table__.columns

    for row in rows:
        if not all(fits(columns[key], value) for key, value in row.items() if key not in nested):
            raise InvalidDataError(WRONG_VALUE)

    return rows


def check_format(snapshot: Any) -> None:
    """Accepts only the document that take() writes; anything else raises InvalidDataError.

    A collection that is missing counts as empty: only a value of the wrong type is rejected.
    """
    if not isinstance(snapshot, dict):
        raise InvalidDataError(UNREADABLE)

    # True and 1.0 are equal to 1 in Python, so the type is checked as well as the value.
    if type(snapshot.get("format")) is not int or snapshot["format"] != SNAPSHOT_FORMAT:
        raise InvalidDataError(UNREADABLE)

    project = snapshot.get("project", {})

    if not isinstance(project, dict) or set(project) - set(PROJECT_FIELDS):
        raise InvalidDataError(UNREADABLE)

    check_rows([project], Project)

    for terrain in check_rows(snapshot.get("terrains", []), Terrain, ("points",)):
        check_rows(terrain.get("points", []), TerrainPoint)

    for plan in check_rows(snapshot.get("plans", []), Plan, ("rooms", "components")):
        check_rows(plan.get("rooms", []), Room)
        check_rows(plan.get("components", []), StructuralComponent)

    for name, model in FLAT_COLLECTIONS.items():
        check_rows(snapshot.get(name, []), model)

    scene = snapshot.get("scene_settings")

    if scene is not None:
        check_rows([scene], SceneSettings)


def contents_of(snapshot: dict[str, Any]) -> dict[str, int]:
    check_format(snapshot)
    plans = snapshot.get("plans", [])

    return {
        "terrains": len(snapshot.get("terrains", [])),
        "plans": len(plans),
        "rooms": sum(len(plan.get("rooms", [])) for plan in plans),
        "components": sum(len(plan.get("components", [])) for plan in plans),
        **{name: len(snapshot.get(name, [])) for name in FLAT_COLLECTIONS},
    }


class SnapshotWriter:
    """Replaces the contents of a project with the ones of a snapshot."""

    def __init__(self, session: Session, project: Project) -> None:
        self.session = session
        self.project = project

    def apply(self, snapshot: dict[str, Any], with_project_fields: bool = True) -> None:
        check_format(snapshot)
        self._clear()

        if with_project_fields:
            fields = decode_values(Project, snapshot.get("project", {}))
            # Checked before it is set: the query would otherwise flush the old file id.
            fields["cover_file_id"] = self._own_file(fields.get("cover_file_id"))

            for field in PROJECT_FIELDS:
                if field in fields:
                    setattr(self.project, field, fields[field])
        else:
            self.project.cover_file_id = None

        self.project.terrains = [self._terrain(values) for values in snapshot.get("terrains", [])]
        self.project.plans = [self._plan(values) for values in snapshot.get("plans", [])]

        for name, model in FLAT_COLLECTIONS.items():
            setattr(
                self.project,
                name,
                [self._build(model, values) for values in snapshot.get(name, [])],
            )

        scene = snapshot.get("scene_settings")
        self.project.scene_settings = None if scene is None else self._build(SceneSettings, scene)

    def _clear(self) -> None:
        room_ids = list(
            self.session.scalars(select(Room.id).where(Room.project_id == self.project.id))
        )

        # The database would empty these references by itself; SQLite in the tests does not.
        if room_ids:
            for model in (SpatialElement, WalkthroughStep, RenovationLog):
                self.session.execute(
                    update(model).where(model.room_id.in_(room_ids)).values(room_id=None)
                )

        self.project.terrains = []
        self.project.plans = []
        self.project.scene_settings = None

        for name in FLAT_COLLECTIONS:
            setattr(self.project, name, [])

        # Deleting first keeps the unique names (of materials, for instance) free.
        self.session.flush()

    def _build(self, model: type[Base], values: dict[str, Any]) -> Base:
        decoded = decode_values(model, values)

        if "file_id" in decoded:
            decoded["file_id"] = self._own_file(decoded["file_id"])

        if model is Task and decoded.get("assignee_id") not in (None, self.project.owner_id):
            decoded["assignee_id"] = None

        return model(**decoded)

    def _terrain(self, values: dict[str, Any]) -> Terrain:
        values = dict(values)
        points = values.pop("points", [])
        terrain = self._build(Terrain, values)
        terrain.points = [self._build(TerrainPoint, point) for point in points]

        return terrain

    def _plan(self, values: dict[str, Any]) -> Plan:
        values = dict(values)
        rooms = values.pop("rooms", [])
        components = values.pop("components", [])
        plan = self._build(Plan, values)
        plan.rooms = [self._room(room) for room in rooms]
        plan.components = [
            self._build(StructuralComponent, {**component, "project_id": self.project.id})
            for component in components
        ]

        return plan

    def _room(self, values: dict[str, Any]) -> Room:
        unit_id = self._own_unit(values.get("unit_id"))

        return self._build(Room, {**values, "project_id": self.project.id, "unit_id": unit_id})

    def _own_file(self, file_id: int | None) -> int | None:
        if file_id is None:
            return None

        file = self.session.get(File, file_id)

        return file_id if file is not None and file.project_id == self.project.id else None

    def _own_unit(self, unit_id: int | None) -> int | None:
        if unit_id is None:
            return None

        owner = self.session.scalar(
            select(Property.project_id)
            .join(Unit, Unit.property_id == Property.id)
            .where(Unit.id == unit_id)
        )

        return unit_id if owner == self.project.id else None
