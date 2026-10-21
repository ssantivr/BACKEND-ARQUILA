import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import File, Plan, Project, Room, SpatialElement, User

BOX = {"min_x_m": 0, "min_y_m": 0, "min_z_m": 0, "max_x_m": 1, "max_y_m": 1, "max_z_m": 1}
SIZE = {"x_m": 0, "y_m": 0, "width_m": 4, "depth_m": 3, "height_m": 2.5}


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def projects(session):
    user = User(name="Ana", email="ana@example.com")
    first, second = Project(owner=user, name="A"), Project(owner=user, name="B")
    session.add_all([first, second])
    session.commit()

    return first, second


def add_plan(session, project):
    plan = Plan(project_id=project.id, title="Ground")
    session.add(plan)
    session.commit()

    return plan


def test_a_room_cannot_be_on_a_plan_of_another_project(session, projects):
    first, second = projects
    plan = add_plan(session, first)

    session.add(Room(project_id=second.id, plan_id=plan.id, name="Kitchen", **SIZE))

    with pytest.raises(IntegrityError):
        session.commit()


def test_a_file_without_a_project_cannot_be_a_cover(session, projects):
    first, _ = projects
    avatar = File(filename="me.png", storage_path="x", mime_type="image/png", size_bytes=1)
    session.add(avatar)
    session.commit()

    first.cover_file_id = avatar.id

    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_a_room_empties_the_reference_and_keeps_the_project(session, projects):
    first, _ = projects
    room = Room(project_id=first.id, plan_id=add_plan(session, first).id, name="Kitchen", **SIZE)
    session.add(room)
    session.commit()
    element = SpatialElement(
        project_id=first.id, room_id=room.id, layer="finishes", kind="floor", name="Tile", **BOX
    )
    session.add(element)
    session.commit()

    session.delete(room)
    session.commit()
    session.refresh(element)

    assert element.room_id is None
    assert element.project_id == first.id
