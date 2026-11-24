import pytest

from tests.helpers import PASSWORD


@pytest.mark.parametrize("password", ["abcdefgh", "12345678", "a1a1a1a1", "aaaa1111"])
def test_weak_passwords_are_refused(client, password):
    sent = {"name": "Ana", "email": "ana@example.com", "password": password}

    assert client.post("/auth/register", json=sent).status_code == 422


def test_a_password_with_letters_and_numbers_is_accepted(client):
    sent = {"name": "Ana", "email": "ana@example.com", "password": PASSWORD}

    assert client.post("/auth/register", json=sent).status_code == 201


def test_the_summary_counts_plans(client):
    sent = {"name": "Ana", "email": "ana@example.com", "password": PASSWORD}
    client.post("/auth/register", json=sent)
    project = client.post("/projects", json={"name": "Casa"}).json()["id"]
    client.post(f"/projects/{project}/plans", json={"title": "Planta 1"})

    assert client.get("/summary").json()["plans"] == 1
