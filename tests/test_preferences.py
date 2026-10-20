import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import register

DEFAULTS = {
    "theme": "auto",
    "units": "metric",
    "density": "comfortable",
    "reduce_motion": False,
    "preview_quality": "medium",
    "camera_defaults": {},
    "notifications": {},
}


@pytest.fixture
def user(client):
    return register(client)


def test_a_new_user_gets_the_defaults(client, user):
    response = client.get("/users/me/preferences")

    assert response.status_code == 200
    assert response.json() == DEFAULTS


def test_put_saves_what_is_sent_and_keeps_the_rest(client, user):
    response = client.put(
        "/users/me/preferences",
        json={
            "theme": "dark",
            "reduce_motion": True,
            "camera_defaults": {"fov": 60, "height_m": 1.6},
            "notifications": {"tasks": False},
        },
    )

    assert response.status_code == 200
    expected = {
        **DEFAULTS,
        "theme": "dark",
        "reduce_motion": True,
        "camera_defaults": {"fov": 60, "height_m": 1.6},
        "notifications": {"tasks": False},
    }
    assert response.json() == expected
    assert client.get("/users/me/preferences").json() == expected

    again = client.put("/users/me/preferences", json={"units": "imperial"}).json()
    assert again == {**expected, "units": "imperial"}


def test_preferences_belong_to_each_user(client, user):
    client.put("/users/me/preferences", json={"theme": "light"})

    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")

    assert other.get("/users/me/preferences").json()["theme"] == "auto"


@pytest.mark.parametrize(
    "values",
    [
        {"theme": "blue"},
        {"units": "nautical"},
        {"density": "huge"},
        {"preview_quality": "ultra"},
        {"reduce_motion": "sometimes"},
        {"notifications": {"tasks": "yes please"}},
        {"notifications": {f"k{n}": True for n in range(31)}},
        {"camera_defaults": {"notes": "x" * 4000}},
        {"camera_defaults": {"": 1}},
        {"camera_defaults": []},
    ],
)
def test_invalid_preferences_are_rejected(client, user, values):
    assert client.put("/users/me/preferences", json=values).status_code == 422


def test_preferences_need_a_session(client):
    assert client.get("/users/me/preferences").status_code == 401
    assert client.put("/users/me/preferences", json={"theme": "dark"}).status_code == 401
