from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dtos import RoomSpatialUpdate
from app.errors import NotFoundError
from app.models import Room, User
from app.repositories.room_repository import RoomRepository
from app.services.activity_log import field_changes
from app.services.base import ApiScopedService, changes_in
from app.services.property_service import UnitService


class RoomSpatialService(ApiScopedService):
    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.rooms = RoomRepository(session)
        self.units = UnitService(session, user)

    def list(
        self,
        project_id: int,
        unit_id: int | None = None,
        category: str | None = None,
    ) -> list[Room]:
        self._require_project(project_id)

        query = select(Room).where(Room.project_id == project_id)

        if unit_id is not None:
            query = query.where(Room.unit_id == unit_id)

        if category is not None:
            query = query.where(Room.category == category)

        return list(self.session.scalars(query.order_by(Room.id)))

    def get(self, room_id: int) -> Room:
        room = self.rooms.get(room_id)

        if room is None or not self._owns(room.project_id):
            raise NotFoundError("Cuarto no encontrado.")

        return room

    def update(self, room_id: int, data: RoomSpatialUpdate) -> Room:
        room = self.get(room_id)
        changes = changes_in(data, nullable={"unit_id", "mesh_ref"})
        unit_id = changes.get("unit_id")

        if unit_id is not None and self.units.project_of(unit_id) != room.project_id:
            raise NotFoundError("Esa unidad no pertenece al proyecto del cuarto.")

        before, after = field_changes(room, changes)

        for field, value in changes.items():
            setattr(room, field, value)

        if after:
            self._record(
                "updated",
                "room",
                room.project_id,
                room.id,
                room.name,
                fields=sorted(after),
                old_value=before,
                new_value=after,
            )

        return self.rooms.save(room)
