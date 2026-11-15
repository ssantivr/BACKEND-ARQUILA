from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models import ActivityEntry


@dataclass(frozen=True)
class ActivityFilters:
    """Optional filters of the change history; `since` is inclusive and `until` exclusive, both
    UTC instants."""

    entity_type: str | None = None
    origin: str | None = None
    source_module: str | None = None
    user_id: int | None = None
    since: datetime | None = None
    until: datetime | None = None


class ActivityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entry: ActivityEntry) -> ActivityEntry:
        """Adds the entry to the open transaction without committing it.

        The service commits it together with the change it describes, so a change is never saved
        without its entry, nor an entry without its change. The flush sends it now, so a rejected
        entry fails before the change is committed.
        """
        self.session.add(entry)
        self.session.flush()
        return entry

    def latest(self, project_id: int, action: str) -> ActivityEntry | None:
        return self.session.scalar(
            select(ActivityEntry)
            .where(ActivityEntry.project_id == project_id, ActivityEntry.action == action)
            .order_by(ActivityEntry.id.desc())
            .limit(1)
        )

    def page_by_project(
        self,
        project_id: int,
        offset: int,
        limit: int,
        filters: ActivityFilters | None = None,
    ) -> tuple[list[ActivityEntry], int]:
        condition = [ActivityEntry.project_id == project_id, *self._conditions(filters)]
        total = self.session.scalar(select(func.count(ActivityEntry.id)).where(*condition))
        # created_at first so idx_activity_log_project_created can serve the order; id breaks the
        # ties of entries saved in the same instant, newest first.
        query = (
            select(ActivityEntry)
            .where(*condition)
            .order_by(ActivityEntry.created_at.desc(), ActivityEntry.id.desc())
            .offset(offset)
            .limit(limit)
        )

        return list(self.session.scalars(query)), total

    @staticmethod
    def _conditions(filters: ActivityFilters | None) -> list[ColumnElement[bool]]:
        if filters is None:
            return []

        condition: list[ColumnElement[bool]] = []

        if filters.entity_type is not None:
            condition.append(ActivityEntry.entity_type == filters.entity_type)

        if filters.origin is not None:
            condition.append(ActivityEntry.origin == filters.origin)

        if filters.source_module is not None:
            condition.append(ActivityEntry.source_module == filters.source_module)

        if filters.user_id is not None:
            condition.append(ActivityEntry.user_id == filters.user_id)

        if filters.since is not None:
            condition.append(ActivityEntry.created_at >= filters.since)

        if filters.until is not None:
            condition.append(ActivityEntry.created_at < filters.until)

        return condition
