"""The AI project builder (R13): it proposes, the user completes and confirms, undo removes it."""

import json

import pytest

from app.errors import AIUnavailableError
from app.extraction import providers
from app.extraction.builder import read_build
from app.extraction.schemas import (
    MAX_BUILD_DESCRIPTION_LENGTH,
    MAX_LEVELS,
    MAX_ROOMS,
    BuildProposal,
    ProposedLevel,
)
from app.main import app
from app.services.auto_layout import complete_geometry, from_description, lot_dimensions
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
    assert build["fallback"] is False
    [ground, upper] = build["levels"]
    assert ground["fields"]["title"]["value"] == "Planta baja"
    assert ground["rooms"][0]["height_m"]["value"] == 2.6
    # Documentary measures are preserved; generated geometry is explicitly labeled.
    assert ground["rooms"][0]["x_m"]["origin"] == "ai_generated"
    assert "origin" not in ground["rooms"][0]["depth_m"]
    assert ground["rooms"][0]["depth_m"]["source"] == "4 m de fondo"
    assert "origin" not in ground["components"][0]["kind"]
    assert ground["components"][0]["kind"]["source"] == "muro de carga"
    assert upper["rooms"][0]["name"]["value"] == "dormitorio"
    assert build["project"]["name"]["value"] == "Casa"
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


def test_project_and_terrain_fields_need_evidence_in_the_source():
    answer = {
        "project": {
            "name": quoted("Casa moderna", "Casa moderna"),
            "location": quoted("Bogotá", "Bogotá"),
        },
        "terrain": {
            "name": quoted("Lote urbano", "Lote urbano"),
            "area_m2": quoted(200, "200 m²"),
            "width_m": quoted(10, "10 m de ancho"),
            "length_m": quoted(20, "20 m de largo"),
        },
        "levels": [{"title": quoted("Planta baja", "Planta baja")}],
    }

    proposal = read_build(
        json.dumps(answer),
        "description",
        "Casa moderna en Bogotá, lote urbano de 200 m², 10 m de ancho y 20 m de largo.",
    )

    assert proposal.project["name"].value == "Casa moderna"
    assert proposal.project["location"].value == "Bogotá"
    assert proposal.terrain["area_m2"].value == 200
    assert proposal.terrain["width_m"].value == 10
    assert proposal.terrain["length_m"].value == 20


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


def test_document_evidence_is_required_even_with_a_description():
    answer = {
        "levels": [
            {
                "title": quoted("Planta baja", "Planta baja"),
                "rooms": [{"name": quoted("sala", "sala")}],
            }
        ]
    }

    assert read_build(json.dumps(answer), "document", DESCRIPTION).levels == []


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


def test_without_a_provider_text_uses_local_fallback(client, project, use_builder):
    use_builder(None)
    build = propose(client, project, description="Casa de un piso con una sala.").json()
    [level] = build["levels"]
    [room] = level["rooms"]
    assert build["status"] == "review"
    assert build["origin"] == "description"
    assert build["fallback"] is True
    assert build["terrain"]["name"]["origin"] == "ai_generated"
    assert build["terrain"]["area_m2"]["value"] == 200
    assert build["terrain"]["width_m"]["value"] == 10
    assert build["terrain"]["length_m"]["value"] == 20
    assert build["recommendations"]
    assert room["width_m"]["origin"] == "ai_generated"
    assert room["x_m"]["origin"] == "ai_generated"
    file_id = upload(client, project, PDF, "contexto.pdf")
    combined = client.post(
        f"/projects/{project}/builds",
        json={"description": "Casa con cocina.", "file_id": file_id, "consent": True},
    ).json()
    assert combined["fallback"] is True
    assert combined["origin"] == "description"
    assert propose(client, project, file_id=file_id).status_code == 503

    # Consent is still required before sending to an external provider.
    builder = use_builder(FakeBuilder())
    assert propose(client, project, consent=False).status_code == 422
    assert builder.requests == []


@pytest.mark.parametrize(
    "body",
    [
        {"consent": True},
        {"description": ""},
        {"description": "a" * (MAX_BUILD_DESCRIPTION_LENGTH + 1), "consent": True},
    ],
)
def test_it_requires_a_source_and_valid_text(client, project, use_builder, body):
    use_builder(FakeBuilder())

    assert client.post(f"/projects/{project}/builds", json=body).status_code == 422


def test_the_description_is_fenced_as_data(client, project, use_builder):
    builder = use_builder(FakeBuilder())
    propose(client, project)

    [(text, document)] = builder.requests
    assert f"<description>\n{DESCRIPTION}\n</description>" in text
    assert document is None


def test_build_description_limit_is_independent_of_other_text_limits():
    from app.extraction.schemas import BuildCreate

    assert len(BuildCreate(description="x" * MAX_BUILD_DESCRIPTION_LENGTH).description) == 2000
    with pytest.raises(ValueError):
        BuildCreate(description="x" * (MAX_BUILD_DESCRIPTION_LENGTH + 1))


def test_description_and_document_can_be_processed_together(client, project, use_builder):
    builder = use_builder(FakeBuilder())
    file_id = upload(client, project, PDF, "plano.pdf")
    response = client.post(
        f"/projects/{project}/builds",
        json={"description": DESCRIPTION, "file_id": file_id, "consent": True},
    )

    assert response.status_code == 201
    assert response.json()["origin"] == "document"
    [(text, document)] = builder.requests
    assert DESCRIPTION in text
    assert document[0] == PDF


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


def test_confirming_saves_project_terrain_and_recommendations_with_undo(
    client, project, use_builder
):
    use_builder(None)
    build = propose(
        client,
        project,
        description="Casa de dos pisos en lote de 10x20m con una sala.",
    ).json()
    confirmed = CONFIRMED | {
        "project": {"description": "Casa moderna", "location": "Bogotá"},
        "terrain": {
            "name": "Lote principal",
            "area_m2": 200,
            "width_m": 10,
            "length_m": 20,
        },
    }

    applied = client.post(f"/builds/{build['id']}/apply", json=confirmed)

    assert applied.status_code == 200, applied.text
    assert client.get(f"/projects/{project}").json()["description"] == "Casa moderna"
    [terrain] = client.get(f"/projects/{project}/terrains").json()
    assert (terrain["name"], terrain["area_m2"], terrain["width_m"], terrain["length_m"]) == (
        "Lote principal",
        200,
        10,
        20,
    )
    recommendations = client.get(
        f"/projects/{project}/recommendations", params={"source": "system"}
    ).json()
    assert recommendations

    undone = client.post(f"/builds/{build['id']}/undo")

    assert undone.status_code == 200, undone.text
    assert client.get(f"/projects/{project}").json()["description"] is None
    assert client.get(f"/projects/{project}/terrains").json() == []
    assert (
        client.get(f"/projects/{project}/recommendations", params={"source": "system"}).json() == []
    )
    assert counts(client, project) == (0, 0, 0)


def test_undo_refuses_when_generated_terrain_was_changed(client, project, use_builder):
    use_builder(None)
    build = propose(
        client,
        project,
        description="Casa de dos pisos en lote de 10x20m con una sala.",
    ).json()
    confirmed = CONFIRMED | {
        "terrain": {"name": "Lote principal", "area_m2": 200, "width_m": 10, "length_m": 20}
    }
    client.post(f"/builds/{build['id']}/apply", json=confirmed)
    [terrain] = client.get(f"/projects/{project}/terrains").json()
    client.patch(f"/terrains/{terrain['id']}", json={"soil_type": "arcilloso"})

    assert client.post(f"/builds/{build['id']}/undo").status_code == 409
    assert len(client.get(f"/projects/{project}/terrains").json()) == 1


def test_apply_updates_existing_terrain_and_undo_restores_it(client, project, use_builder):
    use_builder(None)
    points = [
        {"x_m": 0, "y_m": 0},
        {"x_m": 12, "y_m": 0},
        {"x_m": 12, "y_m": 20},
        {"x_m": 0, "y_m": 20},
    ]
    terrain_response = client.post(
        f"/projects/{project}/terrains",
        json={"name": "Lote original", "area_m2": 240, "points": points},
    )
    assert terrain_response.status_code == 201
    build = propose(client, project, description="Casa de un piso con una sala.").json()
    confirmed = CONFIRMED | {
        "terrain": {"name": "Lote revisado", "area_m2": 240, "width_m": 12, "length_m": 20}
    }

    applied = client.post(f"/builds/{build['id']}/apply", json=confirmed)

    assert applied.status_code == 200, applied.text
    [updated] = client.get(f"/projects/{project}/terrains").json()
    assert updated["name"] == "Lote revisado"

    undone = client.post(f"/builds/{build['id']}/undo")

    assert undone.status_code == 200, undone.text
    [restored] = client.get(f"/projects/{project}/terrains").json()
    assert restored["name"] == "Lote original"
    assert restored["points"] == points


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


def test_layout_keeps_rooms_disjoint_and_preserves_documented_values():
    documented = quoted(4, "4 m de fondo")
    proposal = BuildProposal(
        origin="description",
        levels=[
            ProposedLevel(
                rooms=[
                    {"name": quoted("sala", "sala"), "depth_m": documented},
                    {"name": quoted("cocina", "cocina")},
                    {"name": quoted("dormitorio", "dormitorio")},
                ]
            )
        ],
    )

    [level] = complete_geometry(proposal, lot_width_m=6, lot_length_m=12).levels
    rectangles = []
    for fields in level.rooms:
        if fields["name"].value == "sala":
            assert fields["depth_m"].source == "4 m de fondo"
        x, y = fields["x_m"].value, fields["y_m"].value
        width, depth = fields["width_m"].value, fields["depth_m"].value
        assert x / 0.15 == pytest.approx(round(x / 0.15))
        assert y / 0.15 == pytest.approx(round(y / 0.15))
        for other_x, other_y, other_width, other_depth in rectangles:
            assert (
                x + width <= other_x
                or other_x + other_width <= x
                or y + depth <= other_y
                or other_y + other_depth <= y
            )
        rectangles.append((x, y, width, depth))


def test_text_fallback_extracts_explicit_dimensions_and_floor_count():
    description = (
        "Casa de dos pisos. Planta baja: sala de 5 m de ancho y 4 m de fondo, altura 2,6 m. "
        "Planta alta: dormitorio."
    )
    proposal = from_description(description, lot_width_m=12, lot_length_m=20)

    assert proposal.fallback is True
    assert len(proposal.levels) == 2
    [ground, upper] = proposal.levels
    [living] = ground.rooms
    assert living["width_m"].value == 5
    assert living["width_m"].source == "5 m de ancho"
    assert living["depth_m"].value == 4
    assert living["depth_m"].source == "4 m de fondo"
    assert living["height_m"].value == 2.6
    assert living["height_m"].source == "altura 2,6 m"
    assert upper.rooms[0]["name"].value == "dormitorio"
    assert lot_dimensions("Lote residencial de 12 x 20 m") == (12, 20)
    assert lot_dimensions("Lote de 12 m de ancho y 20 m de largo") == (12, 20)


def test_text_fallback_expands_room_counts_and_zones_private_rooms_upstairs():
    description = (
        "Casa moderna de 2 pisos en lote de 10x20m con 3 habitaciones, sala-comedor, "
        "cocina integral, 2 baños y patio."
    )

    proposal = from_description(description, lot_width_m=10, lot_length_m=20)

    assert len(proposal.levels) == 2
    [ground, upper] = proposal.levels
    ground_names = [str(room["name"].value).casefold() for room in ground.rooms]
    upper_names = [str(room["name"].value).casefold() for room in upper.rooms]
    assert any("sala-comedor" in name for name in ground_names)
    assert any("cocina" in name for name in ground_names)
    assert any("patio" in name for name in ground_names)
    assert sum("baño" in name for name in ground_names) == 2
    assert sum("habitación" in name or "dormitorio" in name for name in upper_names) == 3

    for level in proposal.levels:
        rectangles = []
        for room_fields in level.rooms:
            x, y = room_fields["x_m"].value, room_fields["y_m"].value
            width, depth = room_fields["width_m"].value, room_fields["depth_m"].value
            for other_x, other_y, other_width, other_depth in rectangles:
                assert (
                    x + width <= other_x
                    or other_x + other_width <= x
                    or y + depth <= other_y
                    or other_y + other_depth <= y
                )
            rectangles.append((x, y, width, depth))


def test_components_are_grid_aligned_and_do_not_overlap_rooms_or_each_other():
    proposal = BuildProposal(
        origin="description",
        levels=[
            ProposedLevel(
                rooms=[{"name": quoted("sala", "sala")}],
                components=[
                    {"kind": quoted("wall", "muro")},
                    {"kind": quoted("column", "columna")},
                ],
            )
        ],
    )

    [level] = complete_geometry(proposal).levels
    room_fields = level.rooms[0]
    room_box = (
        room_fields["x_m"].value,
        room_fields["y_m"].value,
        room_fields["width_m"].value,
        room_fields["depth_m"].value,
    )
    boxes = []
    for fields in level.components:
        box = (
            fields["x_m"].value,
            fields["y_m"].value,
            fields["width_m"].value,
            fields["depth_m"].value,
        )
        x, y, width, depth = box
        assert x / 0.15 == pytest.approx(round(x / 0.15))
        assert y / 0.15 == pytest.approx(round(y / 0.15))
        for other in [room_box, *boxes]:
            ox, oy, ow, od = other
            assert x + width <= ox or ox + ow <= x or y + depth <= oy or oy + od <= y
        boxes.append(box)


def test_generated_room_dimensions_respect_available_lot_bounds():
    proposal = BuildProposal(
        origin="description",
        levels=[ProposedLevel(rooms=[{"name": quoted("sala", "sala")}])],
    )

    [level] = complete_geometry(proposal, lot_width_m=3, lot_length_m=2.4).levels
    [room] = level.rooms
    assert room["width_m"].value == 3
    assert room["depth_m"].value == 2.4


def test_existing_terrain_outline_supplies_lot_dimensions(client, project, use_builder):
    use_builder(None)
    points = [
        {"x_m": 0, "y_m": 0},
        {"x_m": 12, "y_m": 0},
        {"x_m": 12, "y_m": 20},
        {"x_m": 0, "y_m": 20},
    ]
    terrain_response = client.post(
        f"/projects/{project}/terrains",
        json={"name": "Lote", "area_m2": 240, "points": points},
    )
    assert terrain_response.status_code == 201

    build = propose(client, project, description="Casa con una sala.").json()

    assert build["terrain"]["width_m"]["value"] == 12
    assert build["terrain"]["width_m"]["origin"] == "ai_generated"
    assert build["terrain"]["length_m"]["value"] == 20
    assert build["fallback"] is True
