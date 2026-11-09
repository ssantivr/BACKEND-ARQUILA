import json
import logging
import sys

import pytest

from app.logs import JsonFormatter, configure_logging, logger
from tests.helpers import register


class Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.entries = []

    def emit(self, record):
        self.entries.append(json.loads(self.format(record)))

    def events(self, name):
        return [entry for entry in self.entries if entry["event"] == name]


@pytest.fixture
def logs():
    collector = Collector()
    logger.addHandler(collector)
    yield collector
    logger.removeHandler(collector)


def test_each_request_is_logged_as_one_json_line(client, logs):
    client.get("/health?token=secret-value")
    client.get("/missing")

    health, missing = logs.events("request")

    assert health["level"] == "info"
    assert health["method"] == "GET"
    assert health["path"] == "/health"
    assert health["status"] == 200
    assert health["duration_ms"] >= 0
    assert health["time"].endswith("+00:00")
    assert missing["status"] == 404
    assert "secret-value" not in json.dumps(logs.entries)


def test_failed_and_blocked_logins_are_logged_without_credentials(client, logs):
    user = register(client)
    attempt = {"email": user["email"], "password": "wrong-password"}

    for _ in range(5):
        assert client.post("/auth/login", json=attempt).status_code == 401

    assert client.post("/auth/login", json=attempt).status_code == 429

    assert len(logs.events("login_failed")) == 5
    assert len(logs.events("login_blocked")) == 1
    assert all(entry["level"] == "warning" for entry in logs.events("login_failed"))

    written = json.dumps(logs.entries)

    assert "wrong-password" not in written
    assert user["email"] not in written


def test_errors_keep_their_traceback_in_the_entry():
    try:
        raise ValueError("boom")
    except ValueError:
        record = logger.makeRecord(
            logger.name, logging.ERROR, __file__, 0, "request_failed", (), sys.exc_info()
        )

    entry = json.loads(JsonFormatter().format(record))

    assert entry["event"] == "request_failed"
    assert entry["level"] == "error"
    assert "ValueError: boom" in entry["error"]


def test_log_level_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    assert configure_logging().level == logging.WARNING

    monkeypatch.setenv("LOG_LEVEL", "not-a-level")
    assert configure_logging().level == logging.INFO

    monkeypatch.delenv("LOG_LEVEL")
    assert configure_logging().level == logging.INFO


def test_each_response_carries_a_request_id(client):
    generated = client.get("/health").headers["x-request-id"]

    assert len(generated) == 32
    assert (
        client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )
    assert (
        client.get("/health", headers={"X-Request-ID": "bad id\n"}).headers["x-request-id"]
        != "bad id\n"
    )
