import io
import json

import httpx
import pytest
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.errors import AIUnavailableError
from app.extraction import providers
from app.main import app
from app.models import AIExtraction
from app.services import extraction_service
from tests.helpers import register


def make_pdf(pages):
    writer = PdfWriter()

    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


PDF = make_pdf(1)
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (64).to_bytes(4, "big") * 2 + b"\x08\x02"


def found(value, confidence=0.95):
    quote = value if isinstance(value, str) else f"{value} m2, {value} m"
    return {"value": value, "confidence": confidence, "source": f"Página 1: {quote}"}


COMPLETE = {
    "project": {"description": found("Casa de un piso")},
    "terrain": {"name": found("Lote 7"), "area_m2": found(312.5), "width_m": found(12.5)},
    "plan": {"title": found("Planta baja"), "scale": found("1:100")},
}


class FakeExtractor:
    name = "fake"

    def __init__(self, answer=None, external=True, mime_types=("application/pdf", "image/png")):
        self.answer = COMPLETE if answer is None else answer
        self.external = external
        self.mime_types = mime_types
        self.calls = 0

    def extract(self, data, mime_type):
        self.calls += 1

        if isinstance(self.answer, Exception):
            raise self.answer

        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


@pytest.fixture
def use_extractor():
    def use(extractor):
        app.dependency_overrides[providers.get_extractor] = lambda: extractor
        return extractor

    yield use

    app.dependency_overrides.pop(providers.get_extractor, None)


@pytest.fixture
def project(client):
    register(client)
    return client.post("/projects", json={"name": "Casa"}).json()["id"]


def upload(client, project, content=PDF, name="plano.pdf"):
    response = client.post(f"/projects/{project}/files", files={"file": (name, content)})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def read(client, project, file_id=None, consent=True):
    file_id = file_id or upload(client, project)
    body = {"file_id": file_id, "consent": consent}

    return client.post(f"/projects/{project}/extractions", json=body)


def terrains(client, project):
    return client.get(f"/projects/{project}/terrains").json()


def test_without_a_provider_it_says_so_and_changes_nothing(client, project, use_extractor):
    use_extractor(None)

    assert client.get("/extraction/status").json()["available"] is False
    assert read(client, project).status_code == 503
    assert terrains(client, project) == []


@pytest.mark.parametrize(("content", "name"), [(PDF, "plano.pdf"), (PNG, "plano.png")])
def test_a_sure_answer_fills_everything_on_its_own(client, project, use_extractor, content, name):
    use_extractor(FakeExtractor())
    result = read(client, project, upload(client, project, content, name)).json()

    assert result["status"] == "applied"
    assert result["project_fields"] == ["description"]
    assert client.get(f"/projects/{project}").json()["description"] == "Casa de un piso"

    [terrain] = terrains(client, project)
    assert (terrain["id"], terrain["area_m2"]) == (result["terrain_id"], 312.5)
    assert terrain["length_m"] is None
    assert terrain["latitude"] is None

    [plan] = client.get(f"/projects/{project}/plans").json()
    assert (plan["id"], plan["scale"]) == (result["plan_id"], "1:100")


def test_undo_takes_back_everything(client, project, use_extractor):
    use_extractor(FakeExtractor())
    extraction = read(client, project).json()["id"]

    undone = client.post(f"/extractions/{extraction}/undo")

    assert undone.json()["status"] == "undone"
    assert terrains(client, project) == []
    assert client.get(f"/projects/{project}/plans").json() == []
    assert client.get(f"/projects/{project}").json()["description"] is None
    assert client.post(f"/extractions/{extraction}/undo").status_code == 409


def test_undo_never_deletes_what_the_user_did_later(client, project, use_extractor):
    use_extractor(FakeExtractor())
    result = read(client, project).json()
    room = {"plan_id": result["plan_id"], "name": "Sala", "x_m": 0, "y_m": 0}
    room.update(width_m=3, depth_m=3)
    assert client.post(f"/projects/{project}/rooms", json=room).status_code == 201

    assert client.post(f"/extractions/{result['id']}/undo").status_code == 409
    assert len(terrains(client, project)) == 1
    assert len(client.get(f"/projects/{project}/rooms").json()) == 1


def test_undo_stops_when_the_terrain_was_edited(client, project, use_extractor):
    use_extractor(FakeExtractor())
    result = read(client, project).json()
    client.patch(f"/terrains/{result['terrain_id']}", json={"name": "Lote corregido"})

    assert client.post(f"/extractions/{result['id']}/undo").status_code == 409
    assert terrains(client, project)[0]["name"] == "Lote corregido"


@pytest.mark.parametrize(
    "answer",
    [
        {"terrain": {"name": found("Lote 7", 0.6), "area_m2": found(300)}},
        {"terrain": {"name": found("Lote 7"), "width_m": found(12)}},
        {"plan": {"level": found("1")}},
    ],
)
def test_doubtful_or_incomplete_answers_wait_for_review(client, project, use_extractor, answer):
    use_extractor(FakeExtractor(answer))

    result = read(client, project).json()
    assert result["status"] == "review"
    terrain_name = result["proposal"].get("terrain", {}).get("name")
    if terrain_name is not None:
        assert terrain_name["origin"] == "document"
    assert terrains(client, project) == []


def test_what_the_user_wrote_is_not_replaced_without_asking(client, project, use_extractor):
    client.patch(f"/projects/{project}", json={"description": "Mi descripción"})
    use_extractor(FakeExtractor())

    assert read(client, project).json()["status"] == "review"
    assert client.get(f"/projects/{project}").json()["description"] == "Mi descripción"
    assert terrains(client, project) == []


def test_a_reviewed_answer_is_applied_as_corrected(client, project, use_extractor):
    use_extractor(FakeExtractor({"terrain": {"name": found("Lote 7", 0.4)}}))
    extraction = read(client, project).json()["id"]
    body = {"terrain": {"name": "Lote 7A", "area_m2": 250}}

    applied = client.post(f"/extractions/{extraction}/apply", json=body)

    assert applied.json()["status"] == "applied"
    assert terrains(client, project)[0]["name"] == "Lote 7A"
    assert client.post(f"/extractions/{extraction}/apply", json=body).status_code == 409


def test_invented_or_invalid_values_are_dropped(client, project, use_extractor):
    use_extractor(
        FakeExtractor(
            {
                "terrain": {
                    "name": found("Lote 7"),
                    "area_m2": found(-4),
                    "soil_type": {"value": "arcilla", "confidence": 1},
                    "width_m": found("doce"),
                    "latitude": found(4.6),
                },
                "project": {"location": found("x" * 201)},
                "owner_id": 99,
            }
        )
    )

    result = read(client, project).json()

    assert result["status"] == "review"
    assert result["proposal"].keys() == {"terrain"}
    assert result["proposal"]["terrain"].keys() == {"name"}


@pytest.mark.parametrize("answer", ["not json", "[]", {}, AIUnavailableError("down")])
def test_a_failed_reading_changes_nothing(client, project, use_extractor, answer):
    use_extractor(FakeExtractor(answer))

    assert read(client, project).json()["status"] == "failed"
    assert terrains(client, project) == []


def test_nothing_is_sent_out_without_consent(client, project, use_extractor):
    extractor = use_extractor(FakeExtractor())

    assert read(client, project, consent=False).status_code == 422
    assert extractor.calls == 0


def test_a_local_reader_needs_no_consent(client, project, use_extractor):
    use_extractor(FakeExtractor(external=False))

    assert read(client, project, consent=False).status_code == 201


def test_limits_stop_the_document_before_it_is_sent(client, project, use_extractor, monkeypatch):
    extractor = use_extractor(FakeExtractor())
    long_pdf = make_pdf(11)

    assert read(client, project, upload(client, project, long_pdf)).status_code == 422

    monkeypatch.setattr(extraction_service, "MAX_DOCUMENT_BYTES", 10)
    assert read(client, project).status_code == 413
    assert extractor.calls == 0


def test_the_type_must_be_one_the_reader_knows(client, project, use_extractor):
    use_extractor(FakeExtractor(mime_types=("image/png",)))

    assert read(client, project).status_code == 415


def test_the_daily_quota_stops_the_calls(client, project, use_extractor, monkeypatch):
    monkeypatch.setattr(extraction_service, "MAX_PER_DAY", 2)
    extractor = use_extractor(FakeExtractor({}))
    file_id = upload(client, project)

    codes = [read(client, project, file_id).status_code for _ in range(3)]

    assert codes == [201, 201, 429]
    assert extractor.calls == 2


def test_deleting_the_project_does_not_reset_the_quota(
    client, engine, project, use_extractor, monkeypatch
):
    monkeypatch.setattr(extraction_service, "MAX_PER_DAY", 1)
    extractor = use_extractor(FakeExtractor())
    extraction = read(client, project).json()["id"]

    assert client.delete(f"/projects/{project}").status_code == 204
    assert client.post(f"/extractions/{extraction}/undo").status_code == 404

    with Session(engine) as session:
        kept = session.get(AIExtraction, extraction)
        assert (kept.project_id, kept.proposal, kept.snapshot) == (None, None, None)

    other = client.post("/projects", json={"name": "Otra"}).json()["id"]

    assert read(client, other).status_code == 429
    assert extractor.calls == 1


def test_another_user_cannot_see_apply_or_undo(client, project, use_extractor):
    use_extractor(FakeExtractor())
    file_id = upload(client, project)
    extraction = read(client, project, file_id).json()["id"]
    register(client, name="Luis", email="luis@example.com")

    assert client.get(f"/projects/{project}/extractions").status_code == 404
    assert read(client, project, file_id).status_code == 404
    assert client.post(f"/extractions/{extraction}/undo").status_code == 404
    body = {"plan": {"title": "Planta"}}
    assert client.post(f"/extractions/{extraction}/apply", json=body).status_code == 404


def test_a_file_of_another_project_is_not_read(client, project, use_extractor):
    use_extractor(FakeExtractor())
    other = client.post("/projects", json={"name": "Otra"}).json()["id"]

    assert read(client, other, upload(client, project)).status_code == 404


def test_signed_out_requests_are_refused(client):
    assert client.get("/extraction/status").status_code == 401


def test_gemini_gets_the_document_and_keeps_the_key_out_of_the_url():
    seen = []

    def answer(request):
        seen.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    client = httpx.Client(transport=httpx.MockTransport(answer))

    assert (
        providers.GeminiExtractor("secret-key", "a-model", client).extract(PNG, "image/png") == "{}"
    )
    assert "secret-key" not in str(seen[0].url)
    assert seen[0].headers["x-goog-api-key"] == "secret-key"
    assert b"image/png" in seen[0].content


def test_a_provider_error_does_not_show_the_key():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))

    with pytest.raises(AIUnavailableError) as raised:
        providers.GeminiExtractor("secret-key", "a-model", client).extract(PDF, "application/pdf")

    assert "secret-key" not in str(raised.value)


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, None),
        ({"AI_EXTRACTION_PROVIDER": "gemini"}, None),
        (
            {"AI_EXTRACTION_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODEL": "m"},
            "gemini",
        ),
        ({"AI_EXTRACTION_PROVIDER": "ollama", "OLLAMA_VISION_MODEL": "m"}, "ollama"),
    ],
)
def test_the_provider_comes_from_the_environment(monkeypatch, environment, expected):
    for name in ("AI_EXTRACTION_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL", "OLLAMA_VISION_MODEL"):
        monkeypatch.delenv(name, raising=False)

    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    chosen = providers.get_extractor()

    assert (chosen and chosen.name) == expected
