import pytest

from tests.helpers import register

ORIGIN = "http://localhost:5173"


def test_responses_restrict_browser_features(client):
    headers = client.get("/health").headers

    assert headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert "strict-transport-security" not in headers


def test_hsts_is_sent_when_the_cookie_is_https_only(client, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "1")

    headers = client.get("/health").headers

    assert headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_the_preflight_allows_the_methods_of_the_api(client, method):
    response = client.options(
        "/users/me/preferences",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": method},
    )

    assert response.status_code == 200
    assert method in response.headers["access-control-allow-methods"]


def test_the_browser_can_read_the_total_of_a_list(client):
    register(client)

    response = client.get("/projects", headers={"Origin": ORIGIN})

    assert response.headers["access-control-expose-headers"] == "X-Total-Count"
    assert response.headers["x-total-count"] == "0"
