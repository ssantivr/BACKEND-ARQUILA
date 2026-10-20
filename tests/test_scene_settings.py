import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import register

PRESET = {"name": "Entrada", "position": [1, 1.6, 8], "target": [5, 1.2, 0], "fov": 55}
POINT = {"name": "Sala", "position": [2, 1.6, 3], "target": [4, 1.5, 3]}


@pytest.fixture
def project_id(client):
    register(client)
    return client.post("/projects", json={"name": "Demo House"}).json()["id"]


@pytest.fixture
def stranger(client, project_id):
    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    return other


def settings_url(project_id):
    return f"/projects/{project_id}/scene-settings"


def points_url(project_id):
    return f"/projects/{project_id}/walkthrough-points"


def test_a_project_without_settings_answers_empty_ones(client, project_id):
    response = client.get(settings_url(project_id))

    assert response.status_code == 200
    assert response.json() == {
        "project_id": project_id,
        "lighting": {},
        "camera_presets": [],
        "updated_at": None,
    }


def test_save_lighting_and_cameras(client, project_id):
    lighting = {"preset": "sunset", "intensity": 0.8, "shadows": True}

    response = client.put(
        settings_url(project_id), json={"lighting": lighting, "camera_presets": [PRESET]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lighting"] == lighting
    assert body["camera_presets"] == [PRESET]
    assert body["updated_at"] is not None
    assert client.get(settings_url(project_id)).json() == body

    only_lighting = client.put(settings_url(project_id), json={"lighting": {"preset": "noon"}})
    assert only_lighting.json()["lighting"] == {"preset": "noon"}
    assert only_lighting.json()["camera_presets"] == [PRESET]


@pytest.mark.parametrize(
    "values",
    [
        {"lighting": {"intensity": [1, 2]}},
        {"lighting": {"note": "x" * 201}},
        {"lighting": {f"k{n}": 1 for n in range(31)}},
        {"camera_presets": [{**PRESET, "position": [1, 2]}]},
        {"camera_presets": [{**PRESET, "target": [1, 2, "x"]}]},
        {"camera_presets": [{**PRESET, "fov": 5}]},
        {"camera_presets": [{**PRESET, "name": ""}]},
        {"camera_presets": [PRESET] * 21},
    ],
)
def test_invalid_settings_are_rejected(client, project_id, values):
    assert client.put(settings_url(project_id), json=values).status_code == 422


def test_create_list_edit_and_delete_points(client, project_id):
    second = client.post(points_url(project_id), json={**POINT, "name": "Cocina", "sort_order": 2})
    first = client.post(points_url(project_id), json={**POINT, "sort_order": 1})

    assert first.status_code == 201
    point = first.json()
    assert point["position"] == [2, 1.6, 3]
    assert point["target"] == [4, 1.5, 3]
    assert [p["name"] for p in client.get(points_url(project_id)).json()] == ["Sala", "Cocina"]

    edited = client.patch(f"/walkthrough-points/{point['id']}", json={"sort_order": 5})
    assert edited.json()["sort_order"] == 5
    assert [p["name"] for p in client.get(points_url(project_id)).json()] == ["Cocina", "Sala"]
    assert client.get(f"/walkthrough-points/{point['id']}").json() == edited.json()

    assert client.delete(f"/walkthrough-points/{second.json()['id']}").status_code == 204
    assert [p["name"] for p in client.get(points_url(project_id)).json()] == ["Sala"]
    assert client.get(f"/walkthrough-points/{second.json()['id']}").status_code == 404


@pytest.mark.parametrize(
    "values",
    [
        {"name": ""},
        {"position": [1, 2]},
        {"position": [1, 2, 3, 4]},
        {"target": [1, 2, 1e9]},
        {"sort_order": -1},
    ],
)
def test_invalid_points_are_rejected(client, project_id, values):
    assert client.post(points_url(project_id), json={**POINT, **values}).status_code == 422


def test_scene_changes_are_recorded(client, project_id):
    client.put(settings_url(project_id), json={"lighting": {"preset": "noon"}})
    client.post(points_url(project_id), json=POINT)

    items = client.get(f"/projects/{project_id}/activity").json()["items"]

    assert [(i["action"], i["entity_type"]) for i in items[:2]] == [
        ("created", "walkthrough_point"),
        ("updated", "scene_settings"),
    ]


def test_scene_is_kept_in_versions_and_copies(client, project_id):
    client.put(settings_url(project_id), json={"camera_presets": [PRESET]})
    client.post(points_url(project_id), json=POINT)
    version = client.post(f"/projects/{project_id}/versions").json()

    client.put(settings_url(project_id), json={"camera_presets": []})
    for point in client.get(points_url(project_id)).json():
        client.delete(f"/walkthrough-points/{point['id']}")
    client.post(f"/versions/{version['id']}/restore")

    assert client.get(settings_url(project_id)).json()["camera_presets"] == [PRESET]
    assert [p["name"] for p in client.get(points_url(project_id)).json()] == ["Sala"]

    copy = client.post(f"/projects/{project_id}/duplicate").json()
    assert client.get(settings_url(copy["id"])).json()["camera_presets"] == [PRESET]
    assert [p["position"] for p in client.get(points_url(copy["id"])).json()] == [[2, 1.6, 3]]


def test_scene_needs_a_session(client, project_id):
    point = client.post(points_url(project_id), json=POINT).json()
    anonymous = TestClient(app)

    assert anonymous.get(settings_url(project_id)).status_code == 401
    assert anonymous.put(settings_url(project_id), json={}).status_code == 401
    assert anonymous.get(points_url(project_id)).status_code == 401
    assert anonymous.post(points_url(project_id), json=POINT).status_code == 401
    assert anonymous.get(f"/walkthrough-points/{point['id']}").status_code == 401
    assert anonymous.patch(f"/walkthrough-points/{point['id']}", json={}).status_code == 401
    assert anonymous.delete(f"/walkthrough-points/{point['id']}").status_code == 401


def test_scene_of_other_users_is_not_found(client, project_id, stranger):
    point = client.post(points_url(project_id), json=POINT).json()

    assert stranger.get(settings_url(project_id)).status_code == 404
    assert stranger.put(settings_url(project_id), json={}).status_code == 404
    assert stranger.get(points_url(project_id)).status_code == 404
    assert stranger.post(points_url(project_id), json=POINT).status_code == 404
    assert stranger.get(f"/walkthrough-points/{point['id']}").json() == {
        "detail": "Walkthrough point not found"
    }
    assert stranger.patch(f"/walkthrough-points/{point['id']}", json={}).status_code == 404
    assert stranger.delete(f"/walkthrough-points/{point['id']}").status_code == 404
