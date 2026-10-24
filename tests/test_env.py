import json

import pytest

from app import storage
from app.env import check_production_settings, setting
from app.services import state_store
from tests.helpers import PASSWORD, register

SECRET = "a-signing-secret-of-at-least-32-bytes"
FAKE_SECRET = "fake-secret-7f3a9c"


@pytest.fixture(autouse=True)
def without_jwt_secret(monkeypatch):
    # conftest.py already clears the rest of the variables these tests read.
    monkeypatch.delenv("JWT_SECRET", raising=False)


@pytest.fixture(
    params=[("ENVIRONMENT", "production"), ("VERCEL", "1")], ids=["environment", "vercel"]
)
def production(request, monkeypatch):
    variable, value = request.param
    monkeypatch.setenv(variable, value)
    monkeypatch.setenv("JWT_SECRET", SECRET)


def warned(logs):
    return [entry["variable"] for entry in logs.events("insecure_setting")]


def test_development_keeps_the_current_defaults(logs):
    assert setting("COOKIE_SECURE") == "0"
    assert not state_store.keeps_state_in_database()
    assert not storage.keeps_files_in_database()

    check_production_settings()

    assert warned(logs) == []


def test_production_without_variables_uses_the_safe_defaults(production, logs):
    assert setting("COOKIE_SECURE") == "1"
    assert state_store.keeps_state_in_database()
    assert storage.keeps_files_in_database()

    check_production_settings()

    assert warned(logs) == []


def test_an_empty_variable_counts_as_missing(production, monkeypatch):
    monkeypatch.setenv("STATE_STORAGE", "")
    monkeypatch.setenv("COOKIE_SECURE", "  ")

    assert state_store.keeps_state_in_database()
    assert setting("COOKIE_SECURE") == "1"


def test_production_respects_an_explicit_insecure_cookie_and_warns(production, monkeypatch, logs):
    monkeypatch.setenv("COOKIE_SECURE", "0")

    check_production_settings()

    assert setting("COOKIE_SECURE") == "0"
    assert warned(logs) == ["COOKIE_SECURE"]


def test_production_respects_state_in_memory_and_warns(production, monkeypatch, logs):
    monkeypatch.setenv("STATE_STORAGE", "memory")

    check_production_settings()

    assert not state_store.keeps_state_in_database()
    assert warned(logs) == ["STATE_STORAGE"]


def test_files_on_disk_only_warn_on_vercel(monkeypatch, logs):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("FILE_STORAGE", "disk")

    check_production_settings()
    assert not storage.keeps_files_in_database()
    assert warned(logs) == []

    monkeypatch.setenv("VERCEL", "1")
    check_production_settings()
    assert warned(logs) == ["FILE_STORAGE"]


@pytest.mark.parametrize("value", [None, "too-short"])
def test_a_missing_or_short_jwt_secret_only_warns(production, monkeypatch, logs, value):
    if value is None:
        monkeypatch.delenv("JWT_SECRET")
    else:
        monkeypatch.setenv("JWT_SECRET", value)

    check_production_settings()

    assert warned(logs) == ["JWT_SECRET"]


def test_a_warning_never_carries_the_value(production, monkeypatch, logs):
    monkeypatch.setenv("JWT_SECRET", FAKE_SECRET)
    monkeypatch.setenv("COOKIE_SECURE", FAKE_SECRET)
    monkeypatch.setenv("STATE_STORAGE", FAKE_SECRET)

    check_production_settings()

    assert warned(logs) == ["COOKIE_SECURE", "STATE_STORAGE", "JWT_SECRET"]
    assert FAKE_SECRET not in json.dumps(logs.entries)


def test_production_without_variables_sends_a_secure_cookie_and_hsts(client, production):
    response = client.post(
        "/auth/register",
        json={"name": "Ana", "email": "ana@example.com", "password": PASSWORD},
    )

    assert "secure" in response.headers["set-cookie"].lower()
    assert client.get("/health").headers["strict-transport-security"] == "max-age=31536000"


def test_production_with_an_insecure_cookie_sends_neither(client, production, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "0")
    register(client)

    response = client.post("/auth/login", json={"email": "ana@example.com", "password": PASSWORD})

    assert "secure" not in response.headers["set-cookie"].lower()
    assert "strict-transport-security" not in client.get("/health").headers
