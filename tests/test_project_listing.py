import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import register


@pytest.fixture
def projects(client):
    register(client)
    names = ["Lake House", "City Tower", "Beach House", "Old Mill"]
    created = [
        client.post("/projects", json={"name": name, "location": "Quito"}).json() for name in names
    ]
    client.patch(f"/projects/{created[0]['id']}", json={"status": "active", "progress": 80})
    client.patch(
        f"/projects/{created[1]['id']}", json={"description": "Torre junto al lago", "progress": 10}
    )
    client.post(f"/projects/{created[3]['id']}/archive")
    return created


def names(response):
    body = response.json()
    items = body["items"] if isinstance(body, dict) else body
    return [project["name"] for project in items]


def test_without_parameters_the_list_is_the_same_as_before(client, projects):
    response = client.get("/projects")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert names(response) == ["Lake House", "City Tower", "Beach House", "Old Mill"]
    assert response.headers["x-total-count"] == "4"


def test_old_search_and_status_filters_still_return_a_list(client, projects):
    assert names(client.get("/projects", params={"search": "house"})) == [
        "Lake House",
        "Beach House",
    ]
    assert names(client.get("/projects", params={"status": "active"})) == ["Lake House"]


def test_page_returns_items_and_total(client, projects):
    response = client.get("/projects", params={"page": 2, "page_size": 3})

    assert response.status_code == 200
    assert response.json()["total"] == 4
    assert response.json()["page"] == 2
    assert response.json()["page_size"] == 3
    assert names(response) == ["Old Mill"]


def test_page_size_alone_starts_on_the_first_page(client, projects):
    body = client.get("/projects", params={"page_size": 2}).json()

    assert body["page"] == 1
    assert [p["name"] for p in body["items"]] == ["Lake House", "City Tower"]


def test_q_searches_name_description_and_location(client, projects):
    assert names(client.get("/projects", params={"q": "lago"})) == ["City Tower"]
    assert names(client.get("/projects", params={"q": "MILL", "page": 1})) == ["Old Mill"]
    assert len(names(client.get("/projects", params={"q": "quito"}))) == 4
    assert names(client.get("/projects", params={"q": "%"})) == []


def test_archived_filter(client, projects):
    assert names(client.get("/projects", params={"archived": True})) == ["Old Mill"]
    assert "Old Mill" not in names(client.get("/projects", params={"archived": False}))


def test_type_filter_uses_the_properties_of_the_project(client, projects):
    tower = projects[1]["id"]
    client.post(
        "/api/v1/properties",
        json={"project_id": tower, "name": "Torre A", "property_type": "apartment_building"},
    )

    assert names(client.get("/projects", params={"type": "apartment_building"})) == ["City Tower"]
    assert names(client.get("/projects", params={"type": "house"})) == []


@pytest.mark.parametrize(
    ("sort", "order", "expected"),
    [
        ("name", "asc", ["Beach House", "City Tower", "Lake House", "Old Mill"]),
        ("name", "desc", ["Old Mill", "Lake House", "City Tower", "Beach House"]),
        ("progress", "desc", ["Lake House", "City Tower", "Old Mill", "Beach House"]),
        ("id", "desc", ["Old Mill", "Beach House", "City Tower", "Lake House"]),
    ],
)
def test_sort_and_order(client, projects, sort, order, expected):
    assert names(client.get("/projects", params={"sort": sort, "order": order})) == expected


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"sort": "owner_id"},
        {"order": "up"},
        {"type": "castle"},
        {"archived": "maybe"},
        {"q": "x" * 161},
    ],
)
def test_invalid_parameters_are_rejected(client, projects, params):
    assert client.get("/projects", params=params).status_code == 422


def test_listing_requires_a_session(client):
    assert client.get("/projects", params={"page": 1}).status_code == 401


def test_listing_never_shows_projects_of_other_users(client, projects):
    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    other.post("/projects", json={"name": "Foreign House"})

    body = client.get("/projects", params={"page": 1, "q": "house"}).json()

    assert body["total"] == 2
    assert "Foreign House" not in [p["name"] for p in body["items"]]
