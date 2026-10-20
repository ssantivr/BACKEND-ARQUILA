from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SceneSettings, WalkthroughPoint


class SceneRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_settings(self, project_id: int) -> SceneSettings | None:
        return self.session.get(SceneSettings, project_id)

    def get_point(self, point_id: int) -> WalkthroughPoint | None:
        return self.session.get(WalkthroughPoint, point_id)

    def list_points(self, project_id: int) -> list[WalkthroughPoint]:
        query = select(WalkthroughPoint).where(WalkthroughPoint.project_id == project_id)
        order = (WalkthroughPoint.sort_order, WalkthroughPoint.id)
        return list(self.session.scalars(query.order_by(*order)))

    def save[T: (SceneSettings, WalkthroughPoint)](self, item: T) -> T:
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def delete(self, point: WalkthroughPoint) -> None:
        self.session.delete(point)
        self.session.commit()
