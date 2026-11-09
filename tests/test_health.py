from sqlalchemy.exc import OperationalError

from app.database import get_session
from app.main import app


def test_health_check_reports_the_database(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


class BrokenSession:
    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_health_check_fails_when_the_database_is_down(client):
    app.dependency_overrides[get_session] = lambda: BrokenSession()

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}


def test_hsts_is_sent_only_when_the_cookie_is_secure(client, monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    assert "strict-transport-security" not in client.get("/health").headers

    monkeypatch.setenv("COOKIE_SECURE", "1")
    assert client.get("/health").headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
