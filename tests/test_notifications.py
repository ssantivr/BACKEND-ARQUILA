import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Notification
from tests.helpers import register


@pytest.fixture
def user(client):
    return register(client)


@pytest.fixture
def stranger(client, user):
    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    return other


@pytest.fixture
def notifications(engine, user, stranger):
    eve_id = stranger.get("/auth/me").json()["id"]

    with Session(engine) as session:
        session.add_all(
            [
                Notification(user_id=user["id"], title="Primera", body="Hola"),
                Notification(user_id=user["id"], title="Segunda"),
                Notification(user_id=user["id"], title="Tercera"),
                Notification(user_id=eve_id, title="De Eve"),
            ]
        )
        session.commit()
        return {
            notification.title: notification.id
            for notification in session.query(Notification).all()
        }


def titles(response):
    return [item["title"] for item in response.json()]


def test_list_shows_only_own_notifications_newest_first(client, notifications):
    response = client.get("/notifications")

    assert response.status_code == 200
    assert titles(response) == ["Tercera", "Segunda", "Primera"]
    assert response.json()[2]["body"] == "Hola"
    assert response.json()[2]["read_at"] is None


def test_new_user_has_no_notifications(client, user):
    assert client.get("/notifications").json() == []


def test_mark_one_as_read(client, notifications):
    response = client.post(f"/notifications/{notifications['Segunda']}/read")

    assert response.status_code == 200
    assert response.json()["read_at"] is not None

    again = client.post(f"/notifications/{notifications['Segunda']}/read")
    assert again.json()["read_at"] == response.json()["read_at"]

    assert titles(client.get("/notifications", params={"unread": True})) == ["Tercera", "Primera"]


def test_mark_all_as_read(client, stranger, notifications):
    client.post(f"/notifications/{notifications['Primera']}/read")

    response = client.post("/notifications/read-all")

    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    assert client.get("/notifications", params={"unread": True}).json() == []
    assert titles(stranger.get("/notifications", params={"unread": True})) == ["De Eve"]
    assert client.post("/notifications/read-all").json() == {"updated": 0}


def test_limit(client, notifications):
    assert titles(client.get("/notifications", params={"limit": 2})) == ["Tercera", "Segunda"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"unread": "maybe"}])
def test_invalid_parameters_are_rejected(client, notifications, params):
    assert client.get("/notifications", params=params).status_code == 422


def test_notifications_of_other_users_are_not_found(client, notifications):
    response = client.post(f"/notifications/{notifications['De Eve']}/read")

    assert response.status_code == 404
    assert response.json() == {"detail": "Notification not found"}
    assert client.post("/notifications/9999/read").status_code == 404
    assert client.post("/notifications/abc/read").status_code == 422


def test_notifications_need_a_session(client, notifications):
    anonymous = TestClient(app)

    assert anonymous.get("/notifications").status_code == 401
    assert anonymous.post(f"/notifications/{notifications['Primera']}/read").status_code == 401
    assert anonymous.post("/notifications/read-all").status_code == 401
