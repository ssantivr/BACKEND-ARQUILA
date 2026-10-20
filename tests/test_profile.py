import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import User
from app.services import login_limiter
from app.services.login_limiter import password_change_limiter
from tests.helpers import PASSWORD, register

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"
PDF = b"%PDF-1.7\nfake document"
NEW_PASSWORD = "another-long-password"


@pytest.fixture
def user(client):
    return register(client)


@pytest.fixture
def stranger(client, user):
    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    return other


def upload(client, content=PNG, name="me.png"):
    project_id = client.post("/projects", json={"name": f"Project {name}"}).json()["id"]
    return client.post(
        f"/projects/{project_id}/files", files={"file": (name, content, "image/png")}
    ).json()


def change(client, current=PASSWORD, new=NEW_PASSWORD):
    return client.post(
        "/auth/change-password", json={"current_password": current, "new_password": new}
    )


def login(client, password):
    return client.post("/auth/login", json={"email": "ana@example.com", "password": password})


def test_me_has_the_new_profile_fields(client, user):
    me = client.get("/auth/me").json()

    assert me["display_name"] is None
    assert me["avatar_file_id"] is None
    assert user["display_name"] is None


def test_update_display_name_and_avatar(client, user):
    image = upload(client)

    response = client.patch(
        "/auth/me", json={"display_name": "  Arq. Ana  ", "avatar_file_id": image["id"]}
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Arq. Ana"
    assert response.json()["avatar_file_id"] == image["id"]
    assert response.json()["email"] == "ana@example.com"
    assert client.get("/auth/me").json() == response.json()

    cleared = client.patch("/auth/me", json={"display_name": "", "avatar_file_id": None}).json()
    assert cleared["display_name"] is None
    assert cleared["avatar_file_id"] is None


def test_fields_left_out_are_kept(client, user):
    client.patch("/auth/me", json={"display_name": "Ana"})

    assert client.patch("/auth/me", json={}).json()["display_name"] == "Ana"


def test_the_avatar_must_be_an_own_image(client, user, stranger):
    document = upload(client, content=PDF, name="doc.pdf")
    foreign = upload(stranger)

    pdf = client.patch("/auth/me", json={"avatar_file_id": document["id"]})
    assert pdf.status_code == 422
    assert pdf.json() == {"detail": "The avatar must be a PNG, JPEG or WebP image"}

    assert client.patch("/auth/me", json={"avatar_file_id": foreign["id"]}).status_code == 404
    assert client.patch("/auth/me", json={"avatar_file_id": 9999}).status_code == 404


def test_deleting_the_avatar_file_clears_it(client, user):
    image = upload(client)
    client.patch("/auth/me", json={"avatar_file_id": image["id"]})

    client.delete(f"/files/{image['id']}")

    assert client.get("/auth/me").json()["avatar_file_id"] is None


def test_invalid_profile_is_rejected(client, user):
    assert client.patch("/auth/me", json={"display_name": "x" * 121}).status_code == 422
    assert client.patch("/auth/me", json={"avatar_file_id": "abc"}).status_code == 422


def test_profile_needs_a_session(client):
    assert client.patch("/auth/me", json={"display_name": "Ana"}).status_code == 401


def test_change_password_keeps_this_session_and_closes_the_others(client, user):
    other_device = TestClient(app)
    assert login(other_device, PASSWORD).status_code == 200

    response = change(client)

    assert response.status_code == 204
    assert client.get("/auth/me").status_code == 200
    assert other_device.get("/auth/me").status_code == 401
    assert login(TestClient(app), PASSWORD).status_code == 401
    assert login(TestClient(app), NEW_PASSWORD).status_code == 200


def test_change_password_stores_an_argon2_hash(client, user, engine):
    change(client)

    with Session(engine) as session:
        stored = session.scalar(select(User.password_hash).where(User.id == user["id"]))

    assert stored.startswith("$argon2id$")
    assert NEW_PASSWORD not in stored


def test_change_password_leaves_a_notification(client, user):
    change(client)

    notifications = client.get("/notifications").json()

    assert [item["title"] for item in notifications] == ["Contraseña cambiada"]


def test_wrong_current_password_is_rejected(client, user):
    response = change(client, current="not-the-password")

    assert response.status_code == 422
    assert response.json() == {"detail": "The current password is incorrect"}
    assert login(TestClient(app), PASSWORD).status_code == 200


def test_the_new_password_must_be_different_and_long_enough(client, user):
    same = change(client, new=PASSWORD)
    assert same.status_code == 422
    assert same.json() == {"detail": "The new password must be different from the current one"}

    assert change(client, new="short").status_code == 422
    assert change(client, new="x" * 129).status_code == 422


def test_repeated_wrong_passwords_are_blocked(client, user):
    for _ in range(login_limiter.MAX_PASSWORD_CHANGE_FAILURES):
        assert change(client, current="not-the-password").status_code == 422

    blocked = change(client)

    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many failed attempts, try again later"}


def test_the_block_is_kept_in_the_database(client, user, monkeypatch):
    monkeypatch.setenv("STATE_STORAGE", "database")

    for _ in range(login_limiter.MAX_PASSWORD_CHANGE_FAILURES):
        change(client, current="not-the-password")
        password_change_limiter.clear()

    assert change(client).status_code == 429


def test_change_password_needs_a_session(client):
    assert change(client).status_code == 401
