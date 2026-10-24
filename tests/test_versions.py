import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.main import app
from app.models import ProjectVersion
from app.repositories.version_repository import VersionRepository
from app.services.project_snapshot import SnapshotWriter
from tests.helpers import register

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"
POLYGON = [{"x_m": 0, "y_m": 0}, {"x_m": 10, "y_m": 0}, {"x_m": 10, "y_m": 20}]


@pytest.fixture
def project_id(client):
    register(client)
    return client.post("/projects", json={"name": "Demo House", "location": "Quito"}).json()["id"]


@pytest.fixture
def stranger(client, project_id):
    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    return other


def fill(client, project_id):
    file = client.post(
        f"/projects/{project_id}/files", files={"file": ("plan.png", PNG, "image/png")}
    ).json()
    client.post(
        f"/projects/{project_id}/terrains",
        json={"name": "Lote", "area_m2": 200, "points": POLYGON},
    )
    client.post(
        f"/projects/{project_id}/materials",
        json={"name": "Cemento", "unit": "saco", "quantity": 12.5, "unit_cost": 8.75},
    )
    plan = client.post(
        f"/projects/{project_id}/plans", json={"title": "Planta baja", "file_id": file["id"]}
    ).json()
    room = {"plan_id": plan["id"], "name": "Sala", "x_m": 0, "y_m": 0, "width_m": 4, "depth_m": 5}
    client.post(f"/projects/{project_id}/rooms", json=room)
    client.post(
        f"/projects/{project_id}/components",
        json={
            **room,
            "name": "C1",
            "kind": "column",
            "width_m": 0.3,
            "depth_m": 0.3,
            "height_m": 3,
        },
    )
    client.post(
        f"/projects/{project_id}/elevations", json={"title": "Norte", "orientation": "north"}
    )
    client.patch(f"/projects/{project_id}", json={"progress": 30, "cover_file_id": file["id"]})
    return file


def contents(client, project_id):
    return {
        "terrains": [
            (t["name"], t["area_m2"], [(p["x_m"], p["y_m"]) for p in t["points"]])
            for t in client.get(f"/projects/{project_id}/terrains").json()
        ],
        "materials": [
            (m["name"], m["quantity"], m["unit_cost"])
            for m in client.get(f"/projects/{project_id}/materials").json()
        ],
        "plans": [
            (p["title"], p["file_id"] is not None)
            for p in client.get(f"/projects/{project_id}/plans").json()
        ],
        "rooms": [
            (r["name"], r["width_m"]) for r in client.get(f"/projects/{project_id}/rooms").json()
        ],
        "components": [c["name"] for c in client.get(f"/projects/{project_id}/components").json()],
        "elevations": [e["title"] for e in client.get(f"/projects/{project_id}/elevations").json()],
    }


def test_save_list_and_read_a_version(client, project_id):
    fill(client, project_id)

    response = client.post(f"/projects/{project_id}/versions", json={"label": "Anteproyecto"})

    assert response.status_code == 201
    version = response.json()
    assert version["version_number"] == 1
    assert version["label"] == "Anteproyecto"
    assert version["contents"] == {
        "terrains": 1,
        "plans": 1,
        "rooms": 1,
        "components": 1,
        "materials": 1,
        "elevations": 1,
        "tasks": 0,
        "walkthrough_points": 0,
    }

    second = client.post(f"/projects/{project_id}/versions").json()
    assert second["version_number"] == 2
    assert second["label"] is None

    listed = client.get(f"/projects/{project_id}/versions").json()
    assert [item["version_number"] for item in listed] == [2, 1]
    assert "snapshot" not in listed[0]

    detail = client.get(f"/versions/{version['id']}").json()
    assert detail["snapshot"]["format"] == 1
    assert detail["snapshot"]["project"]["progress"] == 30
    assert detail["snapshot"]["materials"][0]["name"] == "Cemento"


def test_restore_brings_back_the_saved_state(client, project_id):
    fill(client, project_id)
    saved = contents(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()

    for material in client.get(f"/projects/{project_id}/materials").json():
        client.delete(f"/materials/{material['id']}")
    for plan in client.get(f"/projects/{project_id}/plans").json():
        client.delete(f"/plans/{plan['id']}")
    client.post(f"/projects/{project_id}/materials", json={"name": "Arena", "unit": "m3"})
    client.patch(f"/projects/{project_id}", json={"progress": 90})

    response = client.post(f"/versions/{version['id']}/restore")

    assert response.status_code == 200
    assert response.json()["progress"] == 30
    assert response.json()["cover_file_id"] is not None
    assert contents(client, project_id) == saved
    assert client.get(f"/projects/{project_id}/undo").json() == []


def test_restore_first_saves_the_current_state(client, project_id):
    fill(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()
    client.post(f"/projects/{project_id}/materials", json={"name": "Arena", "unit": "m3"})

    client.post(f"/versions/{version['id']}/restore")

    versions = client.get(f"/projects/{project_id}/versions").json()
    backup = versions[0]
    assert backup["version_number"] == 2
    assert backup["label"] == "Before restoring version 1"
    assert backup["contents"]["materials"] == 2

    client.post(f"/versions/{backup['id']}/restore")
    names = [m["name"] for m in client.get(f"/projects/{project_id}/materials").json()]
    assert sorted(names) == ["Arena", "Cemento"]


def test_restore_drops_links_to_files_that_are_gone(client, project_id):
    file = fill(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()
    client.delete(f"/files/{file['id']}")

    project = client.post(f"/versions/{version['id']}/restore").json()

    assert project["cover_file_id"] is None
    assert contents(client, project_id)["plans"] == [("Planta baja", False)]


def test_activity_records_saving_and_restoring(client, project_id):
    version = client.post(f"/projects/{project_id}/versions", json={"label": "V1"}).json()
    client.post(f"/versions/{version['id']}/restore")

    items = client.get(f"/projects/{project_id}/activity").json()["items"]

    assert [item["action"] for item in items] == ["version_restored", "version_saved", "created"]

    backup = client.get(f"/projects/{project_id}/versions").json()[0]
    assert items[0]["detail"]["backup_version_id"] == backup["id"]


def test_versions_need_a_session(client, project_id):
    version = client.post(f"/projects/{project_id}/versions").json()
    anonymous = TestClient(app)

    assert anonymous.get(f"/projects/{project_id}/versions").status_code == 401
    assert anonymous.post(f"/projects/{project_id}/versions").status_code == 401
    assert anonymous.get(f"/versions/{version['id']}").status_code == 401
    assert anonymous.post(f"/versions/{version['id']}/restore").status_code == 401


def test_versions_of_other_users_are_not_found(client, project_id, stranger):
    version = client.post(f"/projects/{project_id}/versions").json()

    assert stranger.get(f"/projects/{project_id}/versions").status_code == 404
    assert stranger.post(f"/projects/{project_id}/versions").status_code == 404
    assert stranger.get(f"/versions/{version['id']}").status_code == 404
    assert stranger.post(f"/versions/{version['id']}/restore").status_code == 404
    assert client.get("/versions/9999").json() == {"detail": "Version not found"}


@pytest.mark.parametrize("label", ["", "x" * 161])
def test_invalid_label_is_rejected(client, project_id, label):
    response = client.post(f"/projects/{project_id}/versions", json={"label": label})

    assert response.status_code == 422


def test_duplicate_copies_the_contents_without_files(client, project_id):
    fill(client, project_id)

    response = client.post(f"/projects/{project_id}/duplicate")

    assert response.status_code == 201
    copy = response.json()
    assert copy["name"] == "Demo House (copia)"
    assert copy["location"] == "Quito"
    assert copy["progress"] == 30
    assert copy["cover_file_id"] is None
    assert copy["status"] == "draft"

    original = contents(client, project_id)
    copied = contents(client, copy["id"])
    assert copied["plans"] == [("Planta baja", False)]
    assert {key: value for key, value in copied.items() if key != "plans"} == {
        key: value for key, value in original.items() if key != "plans"
    }
    assert client.get(f"/projects/{copy['id']}/files").json() == []

    again = client.post(f"/projects/{project_id}/duplicate").json()
    assert again["name"] == "Demo House (copia) (2)"


def test_duplicate_accepts_a_name(client, project_id):
    response = client.post(f"/projects/{project_id}/duplicate", json={"name": "Variante B"})

    assert response.status_code == 201
    assert response.json()["name"] == "Variante B"
    assert (
        client.post(f"/projects/{project_id}/duplicate", json={"name": "Variante B"}).status_code
        == 409
    )
    assert client.post(f"/projects/{project_id}/duplicate", json={"name": ""}).status_code == 422


def test_duplicate_of_an_archived_project_is_a_draft(client, project_id):
    client.post(f"/projects/{project_id}/archive")

    copy = client.post(f"/projects/{project_id}/duplicate").json()

    assert copy["status"] == "draft"
    assert copy["archived_at"] is None


def test_duplicate_is_recorded_and_needs_an_own_project(client, project_id, stranger):
    copy = client.post(f"/projects/{project_id}/duplicate").json()
    items = client.get(f"/projects/{copy['id']}/activity").json()["items"]

    assert items[0]["action"] == "duplicated"
    assert items[0]["detail"]["source_project_id"] == project_id
    assert stranger.post(f"/projects/{project_id}/duplicate").status_code == 404
    assert TestClient(app).post(f"/projects/{project_id}/duplicate").status_code == 401


def test_restore_unlinks_the_spatial_elements_of_replaced_rooms(client, project_id):
    plan = client.post(f"/projects/{project_id}/plans", json={"title": "Planta"}).json()
    room = client.post(
        f"/projects/{project_id}/rooms",
        json={
            "plan_id": plan["id"],
            "name": "Baño",
            "x_m": 0,
            "y_m": 0,
            "width_m": 2,
            "depth_m": 2,
        },
    ).json()
    element = client.post(
        "/api/v1/spatial-data/elements",
        json={
            "project_id": project_id,
            "room_id": room["id"],
            "layer": "installations",
            "kind": "water_pipe",
            "name": "Tubería",
            "min_x_m": 0,
            "min_y_m": 0,
            "min_z_m": 0,
            "max_x_m": 1,
            "max_y_m": 0.1,
            "max_z_m": 0.1,
        },
    ).json()
    version = client.post(f"/projects/{project_id}/versions").json()

    client.post(f"/versions/{version['id']}/restore")

    kept = client.get(f"/api/v1/spatial-data/elements/{element['id']}")
    assert kept.status_code == 200
    assert kept.json()["room_id"] is None
    assert [r["name"] for r in client.get(f"/projects/{project_id}/rooms").json()] == ["Baño"]


def store(engine, version_id, change):
    """Writes a snapshot that the API itself would never save."""
    with Session(engine) as session:
        version = session.get(ProjectVersion, version_id)
        version.snapshot = change(copy.deepcopy(version.snapshot))
        # True and 1.0 compare equal to 1, so the change has to be marked to be written at all.
        flag_modified(version, "snapshot")
        session.commit()


def test_a_version_in_an_unknown_format_is_listed_empty_and_cannot_be_opened(
    client, engine, project_id
):
    fill(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()
    # What earlier seeds wrote: a summary with counts instead of the rows.
    store(engine, version["id"], lambda _: {"name": "Demo House", "plans": 1, "rooms": 1})

    listed = client.get(f"/projects/{project_id}/versions")

    assert listed.status_code == 200
    assert [item["contents"] for item in listed.json()] == [{}]
    assert client.get(f"/versions/{version['id']}").status_code == 422
    assert client.post(f"/versions/{version['id']}/restore").status_code == 422
    # Rejected before the backup is saved, so nothing is left behind.
    assert len(client.get(f"/projects/{project_id}/versions").json()) == 1


def test_a_version_without_some_collections_counts_them_as_empty(client, engine, project_id):
    fill(client, project_id)
    saved = contents(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()

    def leave_out(snapshot):
        for name in ("tasks", "walkthrough_points", "scene_settings"):
            del snapshot[name]
        return snapshot

    store(engine, version["id"], leave_out)

    listed = client.get(f"/projects/{project_id}/versions").json()
    assert listed[0]["contents"]["tasks"] == 0
    assert listed[0]["contents"]["walkthrough_points"] == 0
    assert listed[0]["contents"]["materials"] == 1

    assert client.post(f"/versions/{version['id']}/restore").status_code == 200
    assert contents(client, project_id) == saved


@pytest.mark.parametrize(
    "change",
    [
        lambda snapshot: snapshot["materials"][0].update(id=1),
        lambda snapshot: snapshot["plans"][0]["rooms"][0].update(project_id=1),
        lambda snapshot: snapshot["terrains"][0]["points"][0].update(terrain_id=1),
        lambda snapshot: snapshot["materials"][0].update(not_a_column=1),
        lambda snapshot: snapshot.update(plans={}),
        lambda snapshot: snapshot.update(format=True),
        lambda snapshot: snapshot.update(format=1.0),
    ],
    ids=[
        "id",
        "project_id",
        "terrain_id",
        "column-not-in-the-model",
        "plans-not-a-list",
        "format-true",
        "format-float",
    ],
)
def test_a_version_with_rows_that_take_never_writes_is_rejected(client, engine, project_id, change):
    fill(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()
    store(engine, version["id"], lambda snapshot: change(snapshot) or snapshot)

    assert client.get(f"/versions/{version['id']}").status_code == 422
    assert client.post(f"/versions/{version['id']}/restore").status_code == 422
    assert len(client.get(f"/projects/{project_id}/versions").json()) == 1


def changed_after_saving(client, project_id):
    """Saves a version, then changes the project, so that a restore would undo the change."""
    fill(client, project_id)
    version = client.post(f"/projects/{project_id}/versions", json={"label": "V1"}).json()

    for material in client.get(f"/projects/{project_id}/materials").json():
        client.delete(f"/materials/{material['id']}")

    return version, contents(client, project_id)


def assert_nothing_restored(client, project_id, before):
    assert contents(client, project_id) == before
    assert [v["label"] for v in client.get(f"/projects/{project_id}/versions").json()] == ["V1"]
    activity = client.get(f"/projects/{project_id}/activity").json()["items"]
    assert "version_restored" not in [item["action"] for item in activity]


@pytest.mark.parametrize(
    "change",
    [
        lambda snapshot: snapshot["project"].update(progress=150),
        lambda snapshot: snapshot["materials"].append(dict(snapshot["materials"][0])),
    ],
    ids=["progress-over-100", "repeated-material-name"],
)
def test_a_version_that_breaks_a_rule_of_the_database_is_rejected_whole(
    client, engine, project_id, change
):
    version, before = changed_after_saving(client, project_id)
    store(engine, version["id"], lambda snapshot: change(snapshot) or snapshot)

    assert client.post(f"/versions/{version['id']}/restore").status_code == 422
    assert_nothing_restored(client, project_id, before)


def test_a_failure_while_rebuilding_leaves_everything_as_it_was(client, project_id, monkeypatch):
    version, before = changed_after_saving(client, project_id)

    def broken_plan(self, values):
        raise RuntimeError("simulated failure while rebuilding a plan")

    monkeypatch.setattr(SnapshotWriter, "_plan", broken_plan)

    with pytest.raises(RuntimeError):
        client.post(f"/versions/{version['id']}/restore")

    monkeypatch.undo()
    assert_nothing_restored(client, project_id, before)


def test_a_failure_while_committing_leaves_everything_as_it_was(client, project_id, monkeypatch):
    version, before = changed_after_saving(client, project_id)
    apply = SnapshotWriter.apply

    def apply_then_lose_the_connection(self, snapshot, **options):
        apply(self, snapshot, **options)

        def commit():
            raise OperationalError("COMMIT", {}, Exception("simulated: the connection was lost"))

        # Only the session of this request: the writes are done and the commit never happens.
        self.session.commit = commit

    monkeypatch.setattr(SnapshotWriter, "apply", apply_then_lose_the_connection)

    with pytest.raises(OperationalError):
        client.post(f"/versions/{version['id']}/restore")

    monkeypatch.undo()
    assert_nothing_restored(client, project_id, before)


def test_a_backup_that_takes_a_number_in_use_is_a_conflict(client, project_id, monkeypatch):
    version, before = changed_after_saving(client, project_id)
    # What two saves at the same time would do: both pick the number that comes next.
    monkeypatch.setattr(VersionRepository, "next_number", lambda self, project_id: 1)

    response = client.post(f"/versions/{version['id']}/restore")

    assert response.status_code == 409
    monkeypatch.undo()
    assert_nothing_restored(client, project_id, before)


def test_restore_drops_links_to_files_deleted_after_saving(client, project_id):
    file = fill(client, project_id)
    client.post(
        f"/projects/{project_id}/elevations",
        json={"title": "Sur", "orientation": "south", "file_id": file["id"]},
    )
    version = client.post(f"/projects/{project_id}/versions").json()
    client.delete(f"/files/{file['id']}")

    response = client.post(f"/versions/{version['id']}/restore")

    assert response.status_code == 200
    assert response.json()["cover_file_id"] is None
    assert [p["file_id"] for p in client.get(f"/projects/{project_id}/plans").json()] == [None]
    elevations = client.get(f"/projects/{project_id}/elevations").json()
    assert {e["title"]: e["file_id"] for e in elevations} == {"Norte": None, "Sur": None}


def test_restore_does_not_link_a_file_of_another_project(client, engine, project_id):
    fill(client, project_id)
    other = client.post("/projects", json={"name": "Otra casa"}).json()["id"]
    foreign = client.post(
        f"/projects/{other}/files", files={"file": ("other.png", PNG, "image/png")}
    ).json()
    version = client.post(f"/projects/{project_id}/versions").json()

    def point_at_the_other_file(snapshot):
        snapshot["plans"][0]["file_id"] = foreign["id"]
        snapshot["project"]["cover_file_id"] = foreign["id"]
        return snapshot

    store(engine, version["id"], point_at_the_other_file)

    response = client.post(f"/versions/{version['id']}/restore")

    assert response.status_code == 200
    assert response.json()["cover_file_id"] is None
    assert [p["file_id"] for p in client.get(f"/projects/{project_id}/plans").json()] == [None]
