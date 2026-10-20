from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from threading import Lock
from typing import Any

from sqlalchemy import Table
from sqlalchemy.orm import Session

from app.data_structures import DoublyLinkedList, Stack
from app.database import Base
from app.services import state_store

MAX_ENTRIES_PER_PROJECT = 20
STATE_SCOPE = "undo"


@dataclass(frozen=True)
class DeletedRecord:
    project_id: int
    kind: str
    label: str
    model: type[Base]
    values: dict[str, Any]
    children: dict[str, list[tuple[type[Base], dict[str, Any]]]] = field(default_factory=dict)


def column_values(instance: Base, parent: Table | None = None) -> dict[str, Any]:
    return {
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
        if not column.primary_key
        and not any(key.column.table is parent for key in column.foreign_keys)
    }


def snapshot(kind: str, label: str, instance: Base, include: Iterable[str] = ()) -> DeletedRecord:
    values = column_values(instance)
    children = {
        name: [
            (type(child), column_values(child, instance.__table__))
            for child in getattr(instance, name)
        ]
        for name in include
    }

    return DeletedRecord(
        project_id=values["project_id"],
        kind=kind,
        label=label,
        model=type(instance),
        values=values,
        children=children,
    )


@dataclass(frozen=True)
class RestoredRecord:
    deleted: DeletedRecord
    restored_id: int


def model_named(table_name: str) -> type[Base]:
    for mapper in Base.registry.mappers:
        if mapper.class_.__tablename__ == table_name:
            return mapper.class_

    raise LookupError(f"No model is stored in the table {table_name}")


def encode_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    return value


def encode_values(values: dict[str, Any]) -> dict[str, Any]:
    return {name: encode_value(value) for name, value in values.items()}


def decode_values(model: type[Base], values: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(values)

    for column in model.__table__.columns:
        value = decoded.get(column.name)

        if not isinstance(value, str):
            continue

        try:
            python_type = column.type.python_type
        except NotImplementedError:
            continue

        if python_type is datetime:
            decoded[column.name] = datetime.fromisoformat(value)
        elif python_type is date:
            decoded[column.name] = date.fromisoformat(value)
        elif python_type is Decimal:
            decoded[column.name] = Decimal(value)

    return decoded


def encode_record(deleted: DeletedRecord) -> dict[str, Any]:
    return {
        "project_id": deleted.project_id,
        "kind": deleted.kind,
        "label": deleted.label,
        "model": deleted.model.__tablename__,
        "values": encode_values(deleted.values),
        "children": {
            name: [[model.__tablename__, encode_values(values)] for model, values in rows]
            for name, rows in deleted.children.items()
        },
    }


def decode_child(table_name: str, values: dict[str, Any]) -> tuple[type[Base], dict[str, Any]]:
    model = model_named(table_name)

    return model, decode_values(model, values)


def decode_record(stored: dict[str, Any]) -> DeletedRecord:
    model = model_named(stored["model"])

    return DeletedRecord(
        project_id=stored["project_id"],
        kind=stored["kind"],
        label=stored["label"],
        model=model,
        values=decode_values(model, stored["values"]),
        children={
            name: [decode_child(table_name, values) for table_name, values in rows]
            for name, rows in stored["children"].items()
        },
    )


def encode_restored(restored: RestoredRecord) -> dict[str, Any]:
    return {"deleted": encode_record(restored.deleted), "restored_id": restored.restored_id}


def decode_restored(stored: dict[str, Any]) -> RestoredRecord:
    return RestoredRecord(decode_record(stored["deleted"]), stored["restored_id"])


def records_of(restorations: Stack[RestoredRecord]) -> list[RestoredRecord]:
    newest_first = []

    while not restorations.is_empty():
        newest_first.append(restorations.pop())

    oldest_first = newest_first[::-1]

    for restored in oldest_first:
        restorations.push(restored)

    return oldest_first


class UndoHistory:
    def __init__(self, capacity: int = MAX_ENTRIES_PER_PROJECT) -> None:
        self._capacity = capacity
        self._by_project: dict[int, DoublyLinkedList[DeletedRecord]] = {}
        self._redo_by_project: dict[int, Stack[RestoredRecord]] = {}
        self._lock = Lock()

    def record(
        self, deleted: DeletedRecord, keep_redo: bool = False, session: Session | None = None
    ) -> None:
        with self._lock:
            self._load(deleted.project_id, session)
            entries = self._by_project.setdefault(deleted.project_id, DoublyLinkedList())
            entries.push_back(deleted)

            if len(entries) > self._capacity:
                entries.pop_front()

            if not keep_redo:
                self._redo_by_project.pop(deleted.project_id, None)

            self._save(deleted.project_id, session)

    def record_restored(self, restored: RestoredRecord, session: Session | None = None) -> None:
        with self._lock:
            self._load(restored.deleted.project_id, session)
            restorations = self._redo_by_project.setdefault(
                restored.deleted.project_id, Stack(capacity=self._capacity)
            )

            if not restorations.is_full():
                restorations.push(restored)

            self._save(restored.deleted.project_id, session)

    def pop_restored(
        self, project_id: int, session: Session | None = None
    ) -> RestoredRecord | None:
        with self._lock:
            self._load(project_id, session)
            restorations = self._redo_by_project.get(project_id)

            if restorations is None or restorations.is_empty():
                return None

            restored = restorations.pop()
            self._save(project_id, session)

            return restored

    def pop_last(self, project_id: int, session: Session | None = None) -> DeletedRecord | None:
        with self._lock:
            self._load(project_id, session)
            entries = self._by_project.get(project_id)

            if entries is None or entries.is_empty():
                return None

            deleted = entries.pop_back()
            self._save(project_id, session)

            return deleted

    def list(self, project_id: int, session: Session | None = None) -> list[DeletedRecord]:
        with self._lock:
            self._load(project_id, session)
            entries = self._by_project.get(project_id)
            return [] if entries is None else list(reversed(entries))

    def forget(self, project_id: int, session: Session | None = None) -> None:
        with self._lock:
            self._by_project.pop(project_id, None)
            self._redo_by_project.pop(project_id, None)
            self._save(project_id, session)

    def _load(self, project_id: int, session: Session | None) -> None:
        if not state_store.is_persistent(session):
            return

        stored = state_store.load(session, STATE_SCOPE, str(project_id)) or {}
        entries: DoublyLinkedList[DeletedRecord] = DoublyLinkedList()
        restorations: Stack[RestoredRecord] = Stack(capacity=self._capacity)

        for record in stored.get("entries", []):
            entries.push_back(decode_record(record))

        for restored in stored.get("redo", [])[-self._capacity :]:
            restorations.push(decode_restored(restored))

        self._by_project[project_id] = entries
        self._redo_by_project[project_id] = restorations

    def _save(self, project_id: int, session: Session | None) -> None:
        if not state_store.is_persistent(session):
            return

        entries = self._by_project.get(project_id)
        restorations = self._redo_by_project.get(project_id)
        stored = {
            "entries": [] if entries is None else [encode_record(record) for record in entries],
            "redo": []
            if restorations is None
            else [encode_restored(restored) for restored in records_of(restorations)],
        }
        is_empty = not stored["entries"] and not stored["redo"]

        state_store.save(session, STATE_SCOPE, str(project_id), None if is_empty else stored)

    def clear(self) -> None:
        with self._lock:
            self._by_project.clear()
            self._redo_by_project.clear()


undo_history = UndoHistory()
