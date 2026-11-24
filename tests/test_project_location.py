import pytest

from tests.helpers import register


@pytest.fixture
def signed_in(client):
    register(client)
    return client


def test_coordinates_are_saved_and_read_back(signed_in):
    sent = {"name": "Casa", "latitude": -0.22, "longitude": -78.5125, "location_zoom": 13}
    created = signed_in.post("/projects", json=sent)

    assert created.status_code == 201
    read = signed_in.get(f"/projects/{created.json()['id']}").json()

    assert read["latitude"] == -0.22
    assert read["longitude"] == -78.5125
    assert read["location_zoom"] == 13


def test_a_project_can_have_no_coordinates(signed_in):
    read = signed_in.post("/projects", json={"name": "Casa"}).json()

    assert read["latitude"] is None
    assert read["longitude"] is None


def test_coordinates_can_be_changed_and_cleared(signed_in):
    project = signed_in.post("/projects", json={"name": "Casa"}).json()
    url = f"/projects/{project['id']}"

    moved = signed_in.patch(url, json={"latitude": 90, "longitude": -180})
    assert (moved.json()["latitude"], moved.json()["longitude"]) == (90, -180)

    cleared = signed_in.patch(url, json={"latitude": None, "longitude": None})
    assert cleared.json()["latitude"] is None


def test_another_change_keeps_the_coordinates(signed_in):
    sent = {"name": "Casa", "latitude": 1, "longitude": 2}
    project = signed_in.post("/projects", json=sent).json()

    renamed = signed_in.patch(f"/projects/{project['id']}", json={"name": "Casa norte"})

    assert renamed.json()["latitude"] == 1


@pytest.mark.parametrize(
    "position",
    [
        {"latitude": 90.1, "longitude": 0},
        {"latitude": 0, "longitude": -180.1},
        {"latitude": 1},
        {"longitude": 1},
        {"latitude": 1, "longitude": None},
        {"latitude": 1, "longitude": 1, "location_zoom": 20},
    ],
)
def test_invalid_positions_are_rejected(signed_in, position):
    project = signed_in.post("/projects", json={"name": "Casa"}).json()

    assert signed_in.post("/projects", json={"name": "Otra", **position}).status_code == 422
    assert signed_in.patch(f"/projects/{project['id']}", json=position).status_code == 422
