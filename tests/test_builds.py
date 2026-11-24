"""The AI project builder (R13): it proposes, the user completes and confirms, undo removes it."""

import json

import pytest

from app.errors import AIUnavailableError
from app.extraction import providers
from app.extraction.builder import read_build
from app.extraction.schemas import MAX_LEVELS, MAX_ROOMS
from app.main import app
from tests.helpers import register
from tests.test_extractions import PDF, PNG, upload

DESCRIPTION = (
    "Casa de dos pisos. Planta baja: sala de 5 m de ancho y 4 m de fondo, altura 2,6 m. "
    "Planta alta: dormitorio de 3,5 m de ancho. Un muro de carga de 0,2 m de espesor."
)


def quoted(value, source, confidence=0.95):
    return {"value": value, "confidence": confidence, "source": source}


ANSWER = {
    "levels": [
        {
            "title": quoted("Planta baja", "Planta baja"),
            "rooms": [
                {
                    "name": quoted("sala", "sala de 5 m de ancho"),
                    "width_m": quoted(5, "sala de 5 m de ancho"),
                    "depth_m": quoted(4, "4 m de fondo"),
                    "height_m": quoted(2.6, "altura 2,6 m"),
                }
            ],
            "components": [
                {
                    "kind": quoted("wall", "muro de carga"),
                    "name": quoted("muro de carga", "Un muro de carga"),
                    "width_m": quoted(0.2, "0,2 m de espesor"),
                }
            ],
        },
        {
            "title": quoted("Planta alta", "Planta alta"),
            "rooms": [{"name": quoted("dormitorio", "dormitorio de 3,5 m de ancho")}],
        },
    ]
}


class FakeBuilder:
    name = "fake"

    def __init__(self, answer=None, external=True, mime_types=("application/pdf", "image/png")):
        self.answer = ANSWER if answer is None else answer
        self.external = external
        self.mime_types = mime_types
        self.requests = []

    def read(self, instructions, text, document, max_tokens=2048):
        self.requests.append((text, document))

        if isinstance(self.answer, Exception):
            raise self.answer

        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


@pytest.fixture
def project(client):
    register(client)
    return client.post("/projects", json={"name": "Casa"}).json()["id"]


@pytest.fixture
def use_builder():
    def use(builder):
        app.dependency_overrides[providers.get_extractor] = lambda: builder
        return builder

    yield use

    app.dependency_overrides.pop(providers.get_extractor, None)


def propose(client, project, description=DESCRIPTION, consent=True, file_id=None):
    body = {"consent": consent}
    body.update({"file_id": file_id} if file_id else {"description": description})

    return client.post(f"/projects/{project}/builds", json=body)


def room(name="sala", **values):
    return {"name": name, "x_m": 0, "y_m": 0, "width_m": 5, "depth_m": 4, "height_m": 2.6} | values


CONFIRMED = {
    "levels": [
        {
            "title": "Planta baja",
            "rooms": [room()],
            "components": [room("muro de carga", kind="wall", width_m=0.2, depth_m=4)],
        },
        {"title": "Planta alta", "rooms": [room("dormitorio", x_m=6, width_m=3.5)]},
    ]
}


def counts(client, project):
    return tuple(
        len(client.get(f"/projects/{project}/{name}").json())
        for name in ("plans", "rooms", "components")
    )


def test_a_description_gives_a_proposal_that_waits_for_review(client, project, use_builder):
    use_builder(FakeBuilder())
    build = propose(client, project).json()

    assert build["status"] == "review"
    assert build["origin"] == "description"
    [ground, upper] = build["levels"]
    assert ground["fields"]["title"]["value"] == "Planta baja"
    assert ground["rooms"][0]["height_m"]["value"] == 2.6
    # Never proposed: positions, and a depth the description does not give.
    assert "x_m" not in ground["rooms"][0]
    assert set(ground["components"][0]) == {"kind", "name", "width_m"}
    assert set(upper["rooms"][0]) == {"name"}
    assert counts(client, project) == (0, 0, 0)


def test_values_that_are_not_in_the_description_are_left_out():
    invented = {
        "levels": [
            {
                "title": quoted("Sótano", "Sótano"),
                "rooms": [
                    {
                        "name": quoted("sala", "sala"),
                        "width_m": quoted(6, "sala de 6 m de ancho"),
                        "depth_m": quoted(4, "estimado 4 m de fondo"),
                        "height_m": quoted(2.6, "altura 2,6"),
                    }
                ],
            }
        ]
    }

    proposal = read_build(json.dumps(invented), "description", DESCRIPTION)

    [level] = proposal.levels
    assert level.fields == {}
    assert set(level.rooms[0]) == {"name"}


def test_a_document_quote_needs_its_page():
    answer = {
        "levels": [
            {
                "title": quoted("Planta baja", "página 1: Planta baja"),
                "rooms": [
                    {
                        "name": quoted("sala", "sala"),
                        "width_m": quoted(5, "página 1: sala 5 m"),
                    }
                ],
            }
        ]
    }

    [level] = read_build(json.dumps(answer), "document", None).levels

    assert level.fields["title"].value == "Planta baja"
    assert set(level.rooms[0]) == {"width_m"}


def test_limits_cut_the_proposal_and_say_so():
    many = {
        "levels": [
            {"rooms": [{"name": quoted("sala", "sala")}] * (MAX_ROOMS + 1)}
            for _ in range(MAX_LEVELS + 1)
        ]
    }

    proposal = read_build(json.dumps(many), "description", "sala")

    assert len(proposal.levels) == MAX_LEVELS
    assert len(proposal.levels[0].rooms) == MAX_ROOMS
    assert proposal.truncated is True


@pytest.mark.parametrize("answer", ["[]", "no es json", '{"levels": "x"}', {"levels": []}])
def test_an_unusable_answer_creates_nothing(client, project, use_builder, answer):
    use_builder(FakeBuilder(answer))
    build = propose(client, project).json()

    assert build["status"] == "failed"
    assert build["levels"] == []
    assert client.post(f"/builds/{build['id']}/apply", json=CONFIRMED).status_code == 409


def test_a_provider_that_fails_leaves_the_manual_path(client, project, use_builder):
    use_builder(FakeBuilder(AIUnavailableError("down")))

    assert propose(client, project).json()["status"] == "failed"


def test_without_a_provider_or_consent_nothing_is_sent(client, project, use_builder):
    use_builder(None)
    assert propose(client, project).status_code == 503

    builder = use_builder(FakeBuilder())
    assert propose(client, project, consent=False).status_code == 422
    assert builder.requests == []


@pytest.mark.parametrize(
    "body",
    [
        {"consent": True},
        {"description": "x", "file_id": 1, "consent": True},
        {"description": ""},
        {"description": "a" * 201, "consent": True},
    ],
)
def test_it_needs_exactly_one_source(client, project, use_builder, body):
    use_builder(FakeBuilder())

    assert client.post(f"/projects/{project}/builds", json=body).status_code == 422


def test_the_description_is_fenced_as_data(client, project, use_builder):
    builder = use_builder(FakeBuilder())
    propose(client, project)

    [(text, document)] = builder.requests
    assert f"<description>\n{DESCRIPTION}\n</description>" in text
    assert document is None


@pytest.mark.parametrize(("content", "name"), [(PDF, "plano.pdf"), (PNG, "plano.png")])
def test_a_document_is_sent_with_its_type(client, project, use_builder, content, name):
    answer = {"levels": [{"title": quoted("Planta baja", "página 1: Planta baja")}]}
    builder = use_builder(FakeBuilder(answer))
    file_id = upload(client, project, content, name)

    build = propose(client, project, file_id=file_id).json()

    assert (build["origin"], build["file_id"], build["status"]) == ("document", file_id, "review")
    assert builder.requests[0][1][0] == content


def test_confirming_creates_everything_in_one_go_and_undo_removes_it(client, project, use_builder):
    use_builder(FakeBuilder())
    build = propose(client, project).json()

    applied = client.post(f"/builds/{build['id']}/apply", json=CONFIRMED)

    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert len(applied.json()["plan_ids"]) == 2
    assert counts(client, project) == (2, 2, 1)
    assert client.post(f"/builds/{build['id']}/apply", json=CONFIRMED).status_code == 409

    undone = client.post(f"/builds/{build['id']}/undo")

    assert undone.json()["status"] == "undone"
    assert counts(client, project) == (0, 0, 0)
    assert client.post(f"/builds/{build['id']}/undo").status_code == 409


def test_a_missing_value_is_refused_and_nothing_is_created(client, project, use_builder):
    use_builder(FakeBuilder())
    build = propose(client, project).json()
    incomplete = {"levels": [{"title": "Planta baja", "rooms": [room(height_m=None)]}]}
    rounded_up = {"levels": [{"title": "Planta baja", "rooms": [room(width_m=999.999)]}]}
    no_position = {"levels": [{"title": "Planta baja", "rooms": [{"name": "sala"}]}]}

    for body in (incomplete, no_position, rounded_up, {"levels": []}):
        assert client.post(f"/builds/{build['id']}/apply", json=body).status_code == 422

    assert counts(client, project) == (0, 0, 0)


def test_undo_refuses_when_the_user_changed_what_was_built(client, project, use_builder):
    use_builder(FakeBuilder())
    build = propose(client, project).json()
    client.post(f"/builds/{build['id']}/apply", json=CONFIRMED)
    [sala, _] = client.get(f"/projects/{project}/rooms").json()

    client.patch(f"/rooms/{sala['id']}", json={"width_m": 7})

    assert client.post(f"/builds/{build['id']}/undo").status_code == 409
    assert counts(client, project) == (2, 2, 1)


def test_undo_refuses_when_the_user_added_a_room(client, project, use_builder):
    use_builder(FakeBuilder())
    build = propose(client, project).json()
    plan_id = client.post(f"/builds/{build['id']}/apply", json=CONFIRMED).json()["plan_ids"][0]

    client.post(f"/projects/{project}/rooms", json=room("baño", plan_id=plan_id))

    assert client.post(f"/builds/{build['id']}/undo").status_code == 409


def test_builds_and_document_readings_stay_apart(client, project, use_builder):
    use_builder(FakeBuilder())
    build = propose(client, project).json()

    assert client.get(f"/projects/{project}/extractions").json() == []
    assert [item["id"] for item in client.get(f"/projects/{project}/builds").json()] == [
        build["id"]
    ]
    assert client.post(f"/extractions/{build['id']}/undo").status_code == 404


def test_another_user_cannot_see_or_apply_a_build(client, project, use_builder):
    use_builder(FakeBuilder())
    build = propose(client, project).json()
    client.post("/auth/logout")
    register(client, "Bea", "bea@example.com")

    assert client.post(f"/builds/{build['id']}/apply", json=CONFIRMED).status_code == 404
    assert client.get(f"/projects/{project}/builds").status_code == 404


@pytest.mark.parametrize(
    ("source", "kept"),
    [("muro de carga", True), ("Casa de dos pisos", False), ("muro estimado", False)],
)
def test_the_kind_needs_a_quote_that_names_it(source, kept):
    answer = {"levels": [{"components": [{"kind": quoted("wall", source)}]}]}
    text = DESCRIPTION + " Un muro estimado."

    levels = read_build(json.dumps(answer), "description", text).levels

    assert bool(levels) is kept
