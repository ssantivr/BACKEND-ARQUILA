from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ActivityEntry


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
        entity_type: str | None = None,
    ) -> tuple[list[ActivityEntry], int]:
        condition = [ActivityEntry.project_id == project_id]

        if entity_type is not None:
            condition.append(ActivityEntry.entity_type == entity_type)

        total = self.session.scalar(select(func.count(ActivityEntry.id)).where(*condition))
        query = (
            select(ActivityEntry)
            .where(*condition)
            .order_by(ActivityEntry.id.desc())
            .offset(offset)
            .limit(limit)
        )

        return list(self.session.scalars(query)), total
