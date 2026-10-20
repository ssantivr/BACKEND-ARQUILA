from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.errors import ConflictError, NotFoundError
from app.models import File, Plan
from app.services.base import ProjectScopedService
from app.services.undo_history import (
    DeletedRecord,
    RestoredRecord,
    snapshot,
    undo_history,
)


class UndoService(ProjectScopedService):
    def list(self, project_id: int) -> list[DeletedRecord]:
        self._ensure_project_exists(project_id)

        return undo_history.list(project_id, self.session)

    def undo_last(self, project_id: int) -> DeletedRecord:
        self._ensure_project_exists(project_id)

        deleted = undo_history.pop_last(project_id, self.session)

        if deleted is None:
            raise NotFoundError("Nothing to undo")

        values = dict(deleted.values)

        if values.get("file_id") is not None and (
            self.session.get(File, values["file_id"]) is None
        ):
            values["file_id"] = None

        if values.get("plan_id") is not None and self.session.get(Plan, values["plan_id"]) is None:
            raise ConflictError(f'Cannot restore "{deleted.label}": its plan no longer exists')

        instance = deleted.model(**values)

        for name, rows in deleted.children.items():
            setattr(instance, name, [model(**row) for model, row in rows])

        try:
            self.session.add(instance)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            undo_history.record(deleted, keep_redo=True, session=self.session)
            raise ConflictError(
                f'Cannot restore "{deleted.label}": it conflicts with existing data'
            ) from None

        undo_history.record_restored(RestoredRecord(deleted, instance.id), self.session)
        self._record("restored", deleted.kind, project_id, instance.id, deleted.label)

        return deleted

    def redo_last(self, project_id: int) -> DeletedRecord:
        self._ensure_project_exists(project_id)

        restored = undo_history.pop_restored(project_id, self.session)

        if restored is None:
            raise NotFoundError("Nothing to redo")

        instance = self.session.get(restored.deleted.model, restored.restored_id)

        if instance is None or instance.project_id != project_id:
            raise NotFoundError("Nothing to redo")

        label = getattr(instance, "name", None) or instance.title
        deleted = snapshot(restored.deleted.kind, label, instance, restored.deleted.children)
        self.session.delete(instance)
        self.session.commit()
        undo_history.record(deleted, keep_redo=True, session=self.session)
        self._record("deleted", deleted.kind, project_id, restored.restored_id, deleted.label)

        return deleted
