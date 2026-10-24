import json

import httpx
import pytest

from app import ai, mailer
from app.errors import AIUnavailableError, NotConfiguredError


class FakeSmtp:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.calls = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *details):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append(
            ("send", message["From"], message["To"], message["Subject"], message.get_content())
        )


@pytest.fixture
def smtp(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSmtp)
    return FakeSmtp


def test_console_mailer_is_used_when_smtp_is_not_configured(monkeypatch, capsys):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)

    chosen = mailer.get_mailer()
    chosen.send("ana@example.com", "Hola", "cuerpo del mensaje")

    assert isinstance(chosen, mailer.ConsoleMailer)
    output = capsys.readouterr().out
    assert "ana@example.com" in output and "cuerpo del mensaje" in output


@pytest.mark.parametrize(("variable", "value"), [("ENVIRONMENT", "production"), ("VERCEL", "1")])
def test_production_never_falls_back_to_the_console(monkeypatch, variable, value):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv(variable, value)

    with pytest.raises(NotConfiguredError):
        mailer.get_mailer()


def test_production_uses_smtp_when_it_is_configured(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

    assert isinstance(mailer.get_mailer(), mailer.SmtpMailer)


def test_smtp_mailer_translates_send_into_smtp_calls(monkeypatch, smtp):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "arquila@example.com")

    chosen = mailer.get_mailer()
    chosen.send("ana@example.com", "Hola", "cuerpo")

    assert isinstance(chosen, mailer.SmtpMailer)
    [server] = smtp.instances
    assert (server.host, server.port) == ("smtp.example.com", 2525)
    assert server.calls == [
        "starttls",
        ("login", "mailer", "secret"),
        ("send", "arquila@example.com", "ana@example.com", "Hola", "cuerpo\n"),
    ]


def test_smtp_mailer_skips_login_without_a_user(monkeypatch, smtp):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.delenv("SMTP_USER", raising=False)

    mailer.get_mailer().send("ana@example.com", "Hola", "cuerpo")

    assert [call for call in smtp.instances[0].calls if call[0] == "login"] == []


def ollama_assistant(handler):
    return ai.OllamaAssistant(httpx.Client(transport=httpx.MockTransport(handler)))


def test_ollama_assistant_sends_the_chat_to_the_first_installed_model(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.test/")
    requests = []

    def handler(request):
        requests.append(request)

        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2"}, {"name": "other"}]})

        return httpx.Response(200, json={"message": {"content": "<think>plan</think> Hola."}})

    reply = ollama_assistant(handler).reply("system prompt", [{"role": "user", "content": "hola"}])

    assert reply == "Hola."
    assert [str(request.url) for request in requests] == [
        "http://ollama.test/api/tags",
        "http://ollama.test/api/chat",
    ]
    assert json.loads(requests[1].content) == {
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hola"},
        ],
        "stream": False,
    }


def test_ollama_assistant_uses_the_configured_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": "  "}})

    assert ollama_assistant(handler).reply("s", []) == ai.EMPTY_REPLY
    assert len(requests) == 1
    assert json.loads(requests[0].content)["model"] == "qwen2.5"


def test_ollama_assistant_turns_failures_into_the_application_error(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    def unreachable(request):
        raise httpx.ConnectError("refused", request=request)

    handlers = [
        unreachable,
        lambda request: httpx.Response(200, json={"models": []}),
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, json={"models": [{"name": "m"}], "unexpected": True}),
    ]

    for handler in handlers:
        with pytest.raises(AIUnavailableError):
            ollama_assistant(handler).reply("s", [])


def test_local_assistant_is_chosen():
    assert isinstance(ai.get_assistant(), ai.OllamaAssistant)


def test_ollama_available_model_prefers_the_configured_one(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    def installed(request):
        return httpx.Response(200, json={"models": [{"name": "llama3.2"}]})

    def empty(request):
        return httpx.Response(200, json={"models": []})

    def unreachable(request):
        raise httpx.ConnectError("refused", request=request)

    assert ollama_assistant(installed).available_model() == "llama3.2"
    assert ollama_assistant(empty).available_model() is None
    assert ollama_assistant(unreachable).available_model() is None

    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5")

    assert ollama_assistant(installed).available_model() == "qwen2.5"
    assert ollama_assistant(unreachable).available_model() is None


def test_ollama_assistant_stops_retrying_for_a_while_after_a_failed_connection(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    attempts = []

    def unreachable(request):
        attempts.append(request)
        raise httpx.ConnectTimeout("timed out", request=request)

    assistant = ollama_assistant(unreachable)

    for _ in range(3):
        with pytest.raises(AIUnavailableError):
            assistant.reply("s", [])

    assert assistant.available_model() is None
    assert len(attempts) == 1

    assistant._unreachable_until = 0.0

    with pytest.raises(AIUnavailableError):
        assistant.reply("s", [])

    assert len(attempts) == 2


def test_ollama_assistant_has_connect_and_read_timeouts():
    timeout = ai.OllamaAssistant()._client.timeout

    assert timeout.connect == ai.CONNECT_TIMEOUT_SECONDS
    assert timeout.read == ai.REQUEST_TIMEOUT_SECONDS


def test_ollama_assistant_turns_a_slow_answer_into_the_application_error(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    attempts = []

    def slow(request):
        attempts.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    assistant = ollama_assistant(slow)

    for _ in range(2):
        with pytest.raises(AIUnavailableError):
            assistant.reply("s", [])

    assert len(attempts) == 2
