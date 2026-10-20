from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import register

EMPTY = {
    "projects": 0,
    "draft_projects": 0,
    "active_projects": 0,
    "archived_projects": 0,
    "terrains": 0,
    "total_area_m2": 0,
    "materials_total_cost": 0,
    "in_progress_projects": 0,
    "completed_projects": 0,
    "materials": 0,
    "plans": 0,
}


def test_summary_requires_authentication(client):
    assert client.get("/summary").status_code == 401


def test_summary_is_empty_for_a_new_user(client):
    register(client)

    assert client.get("/summary").json() == EMPTY


def test_summary_adds_up_only_the_users_own_data(client):
    register(client)
    house = client.post("/projects", json={"name": "House", "status": "active"}).json()["id"]
    tower = client.post("/projects", json={"name": "Tower"}).json()["id"]
    client.post("/projects", json={"name": "Old", "status": "archived"})

    client.post(f"/projects/{house}/terrains", json={"name": "A", "area_m2": 450})
    client.post(f"/projects/{tower}/terrains", json={"name": "B", "area_m2": 120.5})
    client.post(
        f"/projects/{house}/materials",
        json={"name": "Concrete", "unit": "m3", "quantity": 10, "unit_cost": 110.5},
    )
    client.post(
        f"/projects/{tower}/materials",
        json={"name": "Brick", "unit": "u", "quantity": 1000, "unit_cost": 0.28},
    )

    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    foreign = other.post("/projects", json={"name": "Foreign"}).json()["id"]
    other.post(f"/projects/{foreign}/terrains", json={"name": "C", "area_m2": 9999})
    other.post(
        f"/projects/{foreign}/materials",
        json={"name": "Gold", "unit": "kg", "quantity": 5, "unit_cost": 50000},
    )

    assert client.get("/summary").json() == {
        "projects": 3,
        "draft_projects": 1,
        "active_projects": 1,
        "archived_projects": 1,
        "terrains": 2,
        "total_area_m2": 570.5,
        "materials_total_cost": 1385.0,
        "in_progress_projects": 1,
        "completed_projects": 0,
        "materials": 2,
        "plans": 0,
    }
    assert other.get("/summary").json()["projects"] == 1


def test_summary_counts_progress_and_plans(client):
    register(client)
    working = client.post("/projects", json={"name": "Working", "status": "active"}).json()["id"]
    done = client.post("/projects", json={"name": "Done", "status": "active"}).json()["id"]
    shelved = client.post("/projects", json={"name": "Shelved", "status": "active"}).json()["id"]

    client.patch(f"/projects/{working}", json={"progress": 40})
    client.patch(f"/projects/{done}", json={"progress": 100})
    client.post(f"/projects/{shelved}/archive")
    client.post(f"/projects/{working}/plans", json={"title": "Planta baja"})
    client.post(f"/projects/{done}/plans", json={"title": "Planta alta"})

    summary = client.get("/summary").json()

    assert summary["projects"] == 3
    assert summary["in_progress_projects"] == 1
    assert summary["completed_projects"] == 1
    assert summary["archived_projects"] == 1
    assert summary["plans"] == 2
