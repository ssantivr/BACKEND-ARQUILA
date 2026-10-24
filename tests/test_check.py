import smtplib

from app import check
from app.errors import AIUnavailableError
from app.mailer import ConsoleMailer


class FakeAssistant:
    def reply(self, system, messages):
        return "Hola, equipo."


class FakeMailer:
    def __init__(self, failure=None):
        self.failure = failure
        self.sent = []

    def send(self, recipient, subject, body):
        if self.failure:
            raise self.failure

        self.sent.append((recipient, subject, body))


def unavailable():
    raise AIUnavailableError("AI assistant is not configured")


def test_check_assistant_reports_the_reply(monkeypatch):
    monkeypatch.setattr(check, "get_assistant", FakeAssistant)

    assert check.check_assistant() == (True, "Hola, equipo.")


def test_check_assistant_reports_why_it_is_unavailable(monkeypatch):
    monkeypatch.setattr(check, "get_assistant", unavailable)

    passed, detail = check.check_assistant()

    assert not passed
    assert "not configured" in detail


def test_check_mailer_sends_a_test_message(monkeypatch):
    fake = FakeMailer()
    monkeypatch.setattr(check, "get_mailer", lambda: fake)

    passed, detail = check.check_mailer("ana@example.com")

    assert passed
    assert "ana@example.com" in detail
    assert fake.sent == [("ana@example.com", check.MAIL_SUBJECT, check.MAIL_BODY)]


def test_check_mailer_fails_when_mail_is_not_configured(monkeypatch):
    monkeypatch.setattr(check, "get_mailer", ConsoleMailer)

    passed, detail = check.check_mailer("ana@example.com")

    assert not passed
    assert "SMTP_HOST" in detail


def test_check_mailer_fails_in_production_without_smtp(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SMTP_HOST", raising=False)

    passed, detail = check.check_mailer("ana@example.com")

    assert not passed
    assert "SMTP_HOST" in detail


def test_check_mailer_reports_smtp_and_network_errors(monkeypatch):
    for failure in [
        smtplib.SMTPAuthenticationError(535, b"bad credentials"),
        OSError("unreachable"),
    ]:
        monkeypatch.setattr(check, "get_mailer", lambda failure=failure: FakeMailer(failure))

        passed, detail = check.check_mailer("ana@example.com")

        assert not passed
        assert "Could not send" in detail
