from datetime import timedelta

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api.deps import SESSION_COOKIE, client_ip
from app.main import app
from app.services import auth_service, login_limiter
from tests.helpers import PASSWORD, register

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"


def login(client, email="ana@example.com", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_register_logs_the_user_in(client):
    user = register(client)

    assert user["email"] == "ana@example.com"
    assert "password" not in user and "password_hash" not in user
    assert client.get("/auth/me").json() == user


def test_session_cookie_is_http_only(client):
    response = client.post(
        "/auth/register",
        json={"name": "Ana", "email": "ana@example.com", "password": PASSWORD},
    )

    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie


def test_session_cookie_can_be_sent_from_another_site(client, monkeypatch):
    monkeypatch.setenv("COOKIE_SAMESITE", "none")

    response = client.post(
        "/auth/register",
        json={"name": "Ana", "email": "ana@example.com", "password": PASSWORD},
    )

    cookie = response.headers["set-cookie"].lower()
    assert "samesite=none" in cookie
    assert "secure" in cookie

    cleared = client.post("/auth/logout").headers["set-cookie"].lower()
    assert "samesite=none" in cleared
    assert "secure" in cleared


def test_unknown_same_site_value_falls_back_to_lax(client, monkeypatch):
    monkeypatch.setenv("COOKIE_SAMESITE", "anything")

    response = client.post(
        "/auth/register",
        json={"name": "Ana", "email": "ana@example.com", "password": PASSWORD},
    )

    assert "samesite=lax" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Ana", "email": "ana@example.com", "password": "short"},
        {"name": "Ana", "email": "not-an-email", "password": PASSWORD},
        {"name": "", "email": "ana@example.com", "password": PASSWORD},
        {"name": "Ana", "email": "ana@example.com"},
    ],
)
def test_invalid_registration_is_rejected(client, payload):
    assert client.post("/auth/register", json=payload).status_code == 422


def test_duplicate_email_is_rejected_ignoring_case(client):
    register(client)

    response = client.post(
        "/auth/register",
        json={"name": "Other", "email": "ANA@Example.com", "password": PASSWORD},
    )

    assert response.status_code == 409


def test_registering_the_same_email_at_once_is_a_conflict(client, monkeypatch):
    register(client)
    monkeypatch.setattr(
        "app.repositories.user_repository.UserRepository.get_by_email",
        lambda self, email: None,
    )

    response = client.post(
        "/auth/register",
        json={"name": "Other", "email": "ana@example.com", "password": PASSWORD},
    )

    assert response.status_code == 409


def test_login_and_logout(client):
    user = register(client)

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401

    response = login(client, email="  ANA@example.com ")
    assert response.status_code == 200
    assert response.json() == user
    assert client.get("/auth/me").json() == user


def test_wrong_credentials_get_the_same_error(client):
    register(client)
    client.post("/auth/logout")

    wrong_password = login(client, password="wrong-password")
    unknown_email = login(client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert client.get("/auth/me").status_code == 401


def test_logout_invalidates_the_token_on_the_server(client):
    register(client)
    token = client.cookies.get(SESSION_COOKIE)

    client.post("/auth/logout")
    client.cookies.set(SESSION_COOKIE, token)

    assert client.get("/auth/me").status_code == 401


def test_forged_or_expired_sessions_are_rejected(client, monkeypatch):
    client.cookies.set(SESSION_COOKIE, "not-a-real-token")
    assert client.get("/auth/me").status_code == 401
    client.cookies.clear()

    monkeypatch.setattr(auth_service, "SESSION_LIFETIME", timedelta(seconds=-1))
    register(client)

    assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/projects"),
        ("post", "/projects"),
        ("get", "/projects/1"),
        ("delete", "/projects/1"),
        ("get", "/projects/1/terrains"),
        ("get", "/terrains/1"),
        ("get", "/projects/1/materials"),
        ("get", "/projects/1/plans"),
        ("get", "/projects/1/elevations"),
        ("get", "/projects/1/recommendations"),
        ("post", "/projects/1/recommendations/generate"),
        ("get", "/projects/1/files"),
        ("get", "/files/1/content"),
        ("get", "/projects/1/undo"),
        ("post", "/projects/1/undo"),
    ],
)
def test_endpoints_require_authentication(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_users_cannot_reach_each_others_data(client):
    register(client)
    project = client.post("/projects", json={"name": "Demo House"}).json()["id"]
    base = f"/projects/{project}"

    terrain = client.post(f"{base}/terrains", json={"name": "Lot", "area_m2": 100}).json()["id"]
    material = client.post(f"{base}/materials", json={"name": "Brick", "unit": "u"}).json()["id"]
    plan = client.post(f"{base}/plans", json={"title": "Ground"}).json()["id"]
    elevation = client.post(
        f"{base}/elevations", json={"title": "Front", "orientation": "north"}
    ).json()["id"]
    recommendation = client.post(
        f"{base}/recommendations", json={"category": "design", "content": "Keep the tree."}
    ).json()["id"]
    file = client.post(f"{base}/files", files={"file": ("a.png", PNG, "image/png")}).json()["id"]

    intruder = TestClient(app)
    register(intruder, name="Eve", email="eve@example.com")

    assert intruder.get("/projects").json() == []

    for path in (
        base,
        f"{base}/terrains",
        f"{base}/materials",
        f"{base}/plans",
        f"{base}/elevations",
        f"{base}/recommendations",
        f"{base}/files",
        f"{base}/undo",
        f"/terrains/{terrain}",
        f"/materials/{material}",
        f"/plans/{plan}",
        f"/elevations/{elevation}",
        f"/files/{file}",
        f"/files/{file}/content",
    ):
        assert intruder.get(path).status_code == 404, path

    assert intruder.patch(base, json={"name": "Stolen"}).status_code == 404
    assert intruder.patch(f"/terrains/{terrain}", json={"name": "x"}).status_code == 404
    assert intruder.patch(f"/plans/{plan}", json={"title": "x"}).status_code == 404
    assert intruder.post(f"{base}/terrains", json={"name": "x", "area_m2": 1}).status_code == 404
    assert intruder.post(f"{base}/recommendations/generate").status_code == 404
    assert intruder.post(f"{base}/undo").status_code == 404

    for path in (
        f"/terrains/{terrain}",
        f"/materials/{material}",
        f"/plans/{plan}",
        f"/elevations/{elevation}",
        f"/recommendations/{recommendation}",
        f"/files/{file}",
        base,
    ):
        assert intruder.delete(path).status_code == 404, path

    own = intruder.post("/projects", json={"name": "Mine"}).json()["id"]
    attach = intruder.post(f"/projects/{own}/plans", json={"title": "P", "file_id": file})
    assert attach.status_code == 404

    assert client.get(base).json()["name"] == "Demo House"
    assert len(client.get(f"{base}/terrains").json()) == 1
    assert client.get(f"/files/{file}/content").content == PNG


def test_two_users_can_use_the_same_project_name(client):
    register(client)
    assert client.post("/projects", json={"name": "Demo House"}).status_code == 201

    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")

    assert other.post("/projects", json={"name": "Demo House"}).status_code == 201


def test_login_is_blocked_after_repeated_failures(client, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(login_limiter, "now", lambda: clock[0])
    register(client)
    register(client, name="Eve", email="eve@example.com")
    client.post("/auth/logout")

    for _ in range(login_limiter.MAX_FAILED_ATTEMPTS):
        assert login(client, password="wrong-password").status_code == 401

    blocked = login(client)
    assert blocked.status_code == 429
    assert client.get("/auth/me").status_code == 401

    assert login(client, email="eve@example.com").status_code == 200
    client.post("/auth/logout")

    clock[0] += login_limiter.WINDOW_SECONDS + 1
    assert login(client).status_code == 200


def test_successful_login_resets_the_failure_count(client, monkeypatch):
    monkeypatch.setattr(login_limiter, "now", lambda: 1000.0)
    register(client)
    client.post("/auth/logout")

    for _ in range(login_limiter.MAX_FAILED_ATTEMPTS - 1):
        login(client, password="wrong-password")

    assert login(client).status_code == 200

    for _ in range(login_limiter.MAX_FAILED_ATTEMPTS - 1):
        assert login(client, password="wrong-password").status_code == 401

    assert login(client).status_code == 200


def test_login_is_blocked_for_an_address_that_tries_many_accounts(client, monkeypatch):
    monkeypatch.setattr(login_limiter, "now", lambda: 1000.0)
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    attacker = {"X-Forwarded-For": "203.0.113.7"}
    register(client)
    client.post("/auth/logout")

    # Under the limit of each email, but over the limit of the address.
    for attempt in range(login_limiter.MAX_FAILED_ATTEMPTS_PER_IP):
        response = client.post(
            "/auth/login",
            json={"email": f"user{attempt}@example.com", "password": "wrong-password"},
            headers=attacker,
        )
        assert response.status_code == 401

    blocked = client.post(
        "/auth/login", json={"email": "ana@example.com", "password": PASSWORD}, headers=attacker
    )
    assert blocked.status_code == 429

    # Ana, from her own address, is not locked out by what the attacker did.
    allowed = client.post(
        "/auth/login",
        json={"email": "ana@example.com", "password": PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.4"},
    )
    assert allowed.status_code == 200


def sign_up(client, email, address):
    return client.post(
        "/auth/register",
        json={"name": "Ana", "email": email, "password": PASSWORD},
        headers={"X-Forwarded-For": address},
    )


def block_registrations_from(client, address):
    for attempt in range(login_limiter.MAX_REGISTRATIONS_PER_IP):
        sign_up(client, f"user{attempt}@example.com", address)


def test_registration_is_limited_per_address(client, monkeypatch):
    monkeypatch.setattr(login_limiter, "now", lambda: 1000.0)
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")

    for attempt in range(login_limiter.MAX_REGISTRATIONS_PER_IP):
        assert sign_up(client, f"user{attempt}@example.com", "203.0.113.7").status_code == 201

    blocked = sign_up(client, "one-more@example.com", "203.0.113.7")

    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many failed attempts, try again later"}


def test_a_blocked_address_learns_nothing_about_the_email(client, monkeypatch):
    monkeypatch.setattr(login_limiter, "now", lambda: 1000.0)
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    block_registrations_from(client, "203.0.113.7")
    client.cookies.clear()

    taken = sign_up(client, "user0@example.com", "203.0.113.7")
    new = sign_up(client, "nobody-yet@example.com", "203.0.113.7")

    assert taken.status_code == new.status_code == 429
    assert taken.content == new.content
    assert "set-cookie" not in taken.headers and "set-cookie" not in new.headers


def test_registration_works_again_after_the_window(client, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(login_limiter, "now", lambda: clock[0])
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    block_registrations_from(client, "203.0.113.7")

    assert sign_up(client, "later@example.com", "203.0.113.7").status_code == 429

    clock[0] += login_limiter.REGISTRATION_WINDOW_SECONDS + 1

    assert sign_up(client, "later@example.com", "203.0.113.7").status_code == 201


def test_a_blocked_address_does_not_block_another(client, monkeypatch):
    monkeypatch.setattr(login_limiter, "now", lambda: 1000.0)
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    block_registrations_from(client, "203.0.113.7")

    assert sign_up(client, "one-more@example.com", "203.0.113.7").status_code == 429
    assert sign_up(client, "neighbour@example.com", "198.51.100.4").status_code == 201


def test_registering_with_other_emails_does_not_reset_the_count(client, monkeypatch):
    monkeypatch.setattr(login_limiter, "now", lambda: 1000.0)
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    sign_up(client, "ana@example.com", "203.0.113.7")

    # A taken email (409) and new ones (201), mixed: each attempt counts, and none resets it.
    for attempt in range(1, login_limiter.MAX_REGISTRATIONS_PER_IP):
        email = "ana@example.com" if attempt % 2 else f"user{attempt}@example.com"
        assert sign_up(client, email, "203.0.113.7").status_code in (201, 409)

    assert sign_up(client, "fresh@example.com", "203.0.113.7").status_code == 429


@pytest.mark.parametrize(
    ("value", "limit"),
    [
        (None, 10),
        ("25", 25),
        ("1", 1),
        ("0", 10),
        ("-3", 10),
        ("ten", 10),
        ("2.5", 10),
        ("", 10),
    ],
)
def test_the_registration_limit_comes_from_the_environment(monkeypatch, value, limit):
    if value is None:
        monkeypatch.delenv("REGISTRATION_LIMIT_PER_HOUR", raising=False)
    else:
        monkeypatch.setenv("REGISTRATION_LIMIT_PER_HOUR", value)

    assert login_limiter.registration_limit() == limit


def request_from(peer: str, forwarded_for: str | None = None) -> Request:
    headers = [] if forwarded_for is None else [(b"x-forwarded-for", forwarded_for.encode())]

    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_client_ip_ignores_forwarded_for_unless_the_proxy_is_trusted(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    assert client_ip(request_from("10.0.0.1", "203.0.113.7")) == "10.0.0.1"

    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    assert client_ip(request_from("10.0.0.1", "203.0.113.7, 10.0.0.1")) == "203.0.113.7"
    assert client_ip(request_from("10.0.0.1")) == "10.0.0.1"


def test_old_failures_stop_counting(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(login_limiter, "now", lambda: clock[0])
    limiter = login_limiter.LoginLimiter(max_attempts=2, window_seconds=10)

    limiter.record_failure("ana")
    clock[0] = 8
    limiter.record_failure("ana")
    assert limiter.is_blocked("ana")
    assert not limiter.is_blocked("eve")

    clock[0] = 11
    assert not limiter.is_blocked("ana")

    limiter.record_failure("ana")
    assert limiter.is_blocked("ana")

    clock[0] = 30
    assert not limiter.is_blocked("ana")


def test_limiter_stops_tracking_new_keys_when_full(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(login_limiter, "now", lambda: clock[0])
    limiter = login_limiter.LoginLimiter(max_attempts=1, window_seconds=10, max_keys=2)

    limiter.record_failure("a")
    limiter.record_failure("b")
    limiter.record_failure("c")

    assert limiter.is_blocked("a")
    assert limiter.is_blocked("b")
    assert not limiter.is_blocked("c")

    clock[0] = 11
    limiter.record_failure("c")

    assert limiter.is_blocked("c")
    assert not limiter.is_blocked("a")
