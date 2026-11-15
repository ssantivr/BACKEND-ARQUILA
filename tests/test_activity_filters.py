"""Filters, order and source-module contract of the change history (R18, H1 and H4)."""

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.models import ActivityEntry
from app.services.activity_log import SOURCE_MODULES
from tests.helpers import register


@pytest.fixture
def project_id(client):
    register(client)
    return client.post("/projects", json={"name": "Demo House"}).json()["id"]


def activity(client, project_id, **params):
    response = client.get(f"/projects/{project_id}/activity", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def labels(client, project_id, **params):
    return [item["detail"].get("label") for item in activity(client, project_id, **params)["items"]]


def add_entries(engine, project_id, *entries):
    """Entries with a known `created_at`, so a boundary or a tie does not depend on the clock."""
    with Session(engine) as session:
        for label, created_at in entries:
            session.add(
                ActivityEntry(
                    project_id=project_id,
                    action="updated",
                    entity_type="plan",
                    detail={"label": label},
                    created_at=created_at,
                )
            )
        session.commit()


@pytest.mark.parametrize(
    "params",
    [
        {"origin": "robot"},
        {"source_module": "unknown-module"},
        {"user_id": 0},
        {"from": "not-a-date"},
        {"from": "2026-11-14T12:00:00Z", "to": "2026-11-14T12:00:00Z"},
        {"from": "2026-11-14T13:00:00Z", "to": "2026-11-14T12:00:00Z"},
        # Valid ISO values whose conversion to UTC leaves the range of datetime.
        {"from": "0001-01-01T00:00:00+05:00"},
        {"to": "9999-12-31T23:00:00-05:00"},
    ],
)
def test_invalid_filters_are_rejected(client, project_id, params):
    response = client.get(f"/projects/{project_id}/activity", params=params)

    assert response.status_code == 422, response.text


def test_activity_is_filtered_by_origin_module_and_user(client, project_id):
    client.post(
        f"/projects/{project_id}/plans", json={"title": "A"}, headers={"X-Arquila-Module": "plans"}
    )
    client.post(
        f"/projects/{project_id}/plans", json={"title": "B"}, headers={"X-Arquila-Module": "viewer"}
    )
    user_id = activity(client, project_id)["items"][0]["user_id"]

    assert labels(client, project_id, source_module="viewer") == ["B"]
    assert activity(client, project_id, origin="user")["total"] == 3
    assert activity(client, project_id, origin="ai")["total"] == 0
    assert activity(client, project_id, user_id=user_id)["total"] == 3
    assert activity(client, project_id, user_id=user_id + 1)["total"] == 0
    assert labels(client, project_id, source_module="plans", origin="user") == ["A"]


def test_activity_is_filtered_by_a_utc_time_range(client, project_id):
    now = datetime.now(UTC)
    hour = timedelta(hours=1)

    def total(**params):
        return activity(client, project_id, **params)["total"]

    assert total(**{"from": (now - hour).isoformat(), "to": (now + hour).isoformat()}) == 1
    assert total(**{"from": (now + hour).isoformat()}) == 0
    assert total(to=(now - hour).isoformat()) == 0
    # Without an offset the value is UTC.
    assert total(**{"from": (now - hour).replace(tzinfo=None).isoformat()}) == 1
    # With one, the instant counts: in Bogota one hour from now reads five hours earlier on the
    # clock, so a server that dropped the offset would still find the entry.
    bogota = timezone(timedelta(hours=-5))
    assert total(**{"from": (now + hour).astimezone(bogota).isoformat()}) == 0


def test_from_is_included_and_to_is_excluded(client, engine, project_id):
    instant = datetime(2020, 1, 6, 15, 30, tzinfo=UTC)
    add_entries(engine, project_id, ("Edge", instant))
    at = instant.isoformat()
    second = timedelta(seconds=1)

    assert labels(client, project_id, **{"from": at}) == ["Demo House", "Edge"]
    assert labels(client, project_id, to=at) == []
    assert labels(client, project_id, to=(instant + second).isoformat()) == ["Edge"]
    assert labels(client, project_id, **{"from": (instant + second).isoformat()}) == ["Demo House"]


def test_entries_of_the_same_instant_come_newest_id_first(client, engine, project_id):
    instant = datetime(2020, 1, 6, 15, 30, tzinfo=UTC)
    add_entries(engine, project_id, ("First", instant), ("Second", instant), ("Third", instant))

    window = {"from": instant.isoformat(), "to": (instant + timedelta(seconds=1)).isoformat()}

    assert labels(client, project_id, **window) == ["Third", "Second", "First"]


def test_the_newest_instant_comes_first_whatever_the_id(client, engine, project_id):
    early = datetime(2020, 1, 6, 15, 30, tzinfo=UTC)
    # Saved later (higher id) but earlier in time, as an imported entry could be.
    add_entries(engine, project_id, ("Late", early + timedelta(minutes=5)), ("Early", early))

    window = {"from": early.isoformat(), "to": (early + timedelta(hours=1)).isoformat()}

    assert labels(client, project_id, **window) == ["Late", "Early"]


def test_an_unknown_module_is_logged_without_its_value(client, project_id, logs):
    client.post(
        f"/projects/{project_id}/plans",
        json={"title": "Plan"},
        headers={"X-Arquila-Module": "plans-v2"},
    )

    [event] = logs.events("unknown_source_module")

    assert event["level"] == "warning"
    assert event["length"] == len("plans-v2")
    assert "plans-v2" not in str(event)


def test_a_known_or_missing_module_logs_nothing(client, project_id, logs):
    client.post(
        f"/projects/{project_id}/plans", json={"title": "A"}, headers={"X-Arquila-Module": "plans"}
    )
    client.post(f"/projects/{project_id}/plans", json={"title": "B"})

    assert logs.events("unknown_source_module") == []


def test_the_source_modules_match_the_contract_in_decisions():
    """H4 in docs/DECISIONS.md is the contract shared with the frontend's SOURCE_MODULES."""
    text = (Path(__file__).parents[1] / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    section = text.split("### H4 · Source modules", 1)[1].split("\n### ", 1)[0]
    line = next(row for row in section.splitlines() if row.startswith("Modules:"))
    contract = re.findall(r"`([a-z]+)`", line)

    assert len(contract) == 18
    assert sorted(contract) == sorted(SOURCE_MODULES)
