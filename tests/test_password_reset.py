import re
from datetime import timedelta

import pytest

from app.mailer import get_mailer
from app.main import app
from app.services import auth_service, login_limiter
from tests.helpers import PASSWORD, register

NEW_PASSWORD = "a-brand-new-password"


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, recipient, subject, body):
        self.sent.append((recipient, subject, body))

    def last_token(self):
        return re.search(r"reset_token=([\w-]+)", self.sent[-1][2]).group(1)


@pytest.fixture
def mailer(client):
    fake = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: fake
    return fake


def request_reset(client, email="ana@example.com"):
    return client.post("/auth/password-reset", json={"email": email})


def confirm(client, token, password=NEW_PASSWORD):
    return client.post("/auth/password-reset/confirm", json={"token": token, "password": password})


def login(client, password, email="ana@example.com"):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_reset_changes_the_password_and_ends_existing_sessions(client, mailer):
    register(client)

    assert request_reset(client, "  ANA@example.com ").status_code == 204
    recipient, subject, body = mailer.sent[0]
    assert recipient == "ana@example.com"
    assert "http://localhost:5173/?reset_token=" in body

    assert confirm(client, mailer.last_token()).status_code == 204

    assert client.get("/auth/me").status_code == 401
    assert login(client, PASSWORD).status_code == 401
    assert login(client, NEW_PASSWORD).status_code == 200


def test_unknown_email_gets_the_same_answer_and_no_mail(client, mailer):
    assert request_reset(client, "nobody@example.com").status_code == 204
    assert mailer.sent == []


def test_token_works_only_once(client, mailer):
    register(client)
    request_reset(client)
    token = mailer.last_token()

    assert confirm(client, token).status_code == 204
    assert confirm(client, token, "another-password-1").status_code == 400
    assert login(client, NEW_PASSWORD).status_code == 200


def test_a_new_request_invalidates_the_previous_token(client, mailer):
    register(client)
    request_reset(client)
    first = mailer.last_token()
    request_reset(client)
    second = mailer.last_token()

    assert first != second
    assert confirm(client, first).status_code == 400
    assert confirm(client, second).status_code == 204


def test_expired_or_made_up_tokens_are_rejected(client, mailer, monkeypatch):
    register(client)

    assert confirm(client, "not-a-real-token-at-all").status_code == 400

    monkeypatch.setattr(auth_service, "RESET_TOKEN_LIFETIME", timedelta(seconds=-1))
    request_reset(client)

    assert confirm(client, mailer.last_token()).status_code == 400
    assert login(client, PASSWORD).status_code == 200


def test_new_password_must_be_valid(client, mailer):
    register(client)
    request_reset(client)

    assert confirm(client, mailer.last_token(), "short").status_code == 422
    assert login(client, PASSWORD).status_code == 200


def test_reset_token_is_not_stored_in_plain_text(client, mailer):
    register(client)
    request_reset(client)

    assert (
        confirm(client, auth_service.security.hash_session_token(mailer.last_token())).status_code
        == 400
    )


def test_reset_requests_are_limited_per_email(client, mailer, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(login_limiter, "now", lambda: clock[0])
    register(client)
    register(client, name="Eve", email="eve@example.com")

    for _ in range(login_limiter.MAX_RESET_REQUESTS + 2):
        assert request_reset(client).status_code == 204

    assert len(mailer.sent) == login_limiter.MAX_RESET_REQUESTS
    assert confirm(client, mailer.last_token()).status_code == 204

    assert request_reset(client, "eve@example.com").status_code == 204
    assert len(mailer.sent) == login_limiter.MAX_RESET_REQUESTS + 1

    clock[0] += login_limiter.RESET_WINDOW_SECONDS + 1
    request_reset(client)
    assert len(mailer.sent) == login_limiter.MAX_RESET_REQUESTS + 2


def test_a_mail_failure_gets_the_same_answer_as_a_sent_mail(client):
    class BrokenMailer:
        def send(self, recipient, subject, body):
            raise ConnectionRefusedError("mail server is down")

    app.dependency_overrides[get_mailer] = lambda: BrokenMailer()
    register(client)

    assert request_reset(client).status_code == 204


def test_production_without_smtp_refuses_instead_of_printing_the_link(client, monkeypatch, capsys):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    register(client)

    response = request_reset(client)

    assert response.status_code == 503
    assert "reset_token" not in capsys.readouterr().out
