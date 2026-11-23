import io
import json
import time

import pytest
from pypdf import PdfWriter
from pypdf.generic import NameObject, NumberObject
from sqlalchemy.orm import Session

from app.errors import InvalidDataError, TooManyAttemptsError
from app.extraction import capacity, documents, providers
from app.extraction.evidence import is_supported
from app.extraction.proposal import read_proposal
from app.main import app
from app.models import AIExtraction, Project
from tests.helpers import register
from tests.test_extractions import (
    COMPLETE,
    PDF,
    FakeExtractor,
    found,
    make_pdf,
    read,
    terrains,
    upload,
)


@pytest.fixture
def project(client):
    register(client)
    return client.post("/projects", json={"name": "Casa"}).json()["id"]


@pytest.fixture
def use_extractor():
    def use(extractor):
        app.dependency_overrides[providers.get_extractor] = lambda: extractor
        return extractor

    yield use

    app.dependency_overrides.pop(providers.get_extractor, None)


class DuringReading(FakeExtractor):
    """Runs something while the provider works."""

    def __init__(self, during, answer=None):
        super().__init__(answer)
        self.during = during

    def extract(self, data, mime_type):
        self.during()
        return super().extract(data, mime_type)


def test_a_reading_in_progress_cannot_be_applied(client, engine, project, use_extractor):
    codes = []

    def apply_now():
        with Session(engine) as session:
            extraction = session.query(AIExtraction.id).scalar()

        body = {"plan": {"title": "Antes de tiempo"}}
        codes.append(client.post(f"/extractions/{extraction}/apply", json=body).status_code)

    use_extractor(DuringReading(apply_now))

    assert read(client, project).json()["status"] == "applied"
    assert codes == [409]
    assert len(terrains(client, project)) == 1


def test_a_text_written_during_the_reading_is_not_replaced(client, engine, project, use_extractor):
    def write_now():
        with Session(engine) as session:
            session.get(Project, project).description = "La escribió el usuario"
            session.commit()

    use_extractor(DuringReading(write_now))

    assert read(client, project).json()["status"] == "review"
    assert client.get(f"/projects/{project}").json()["description"] == "La escribió el usuario"


def test_a_project_deleted_during_the_reading_keeps_nothing(client, engine, project, use_extractor):
    use_extractor(DuringReading(lambda: client.delete(f"/projects/{project}")))

    assert read(client, project).status_code == 404

    with Session(engine) as session:
        kept = session.query(AIExtraction).one()
        assert (kept.project_id, kept.proposal, kept.snapshot) == (None, None, None)


def test_a_file_deleted_during_the_reading_keeps_nothing(client, project, use_extractor):
    file_id = upload(client, project)
    use_extractor(DuringReading(lambda: client.delete(f"/files/{file_id}")))

    result = read(client, project, file_id).json()

    assert (result["status"], result["proposal"]) == ("failed", {})
    assert terrains(client, project) == []


def test_undo_keeps_a_plan_that_got_a_finish(client, engine, project, use_extractor):
    use_extractor(FakeExtractor())
    result = read(client, project).json()
    url = f"/projects/{project}/structure/volume/{result['plan_id']}/surface"

    assert client.patch(url, json={"surface": "brick"}).status_code == 204
    assert client.post(f"/extractions/{result['id']}/undo").status_code == 409


def test_undo_keeps_a_plan_linked_to_another_file(client, project, use_extractor):
    use_extractor(FakeExtractor())
    result = read(client, project).json()
    other = upload(client, project, name="otro.pdf")
    client.patch(f"/plans/{result['plan_id']}", json={"file_id": other})

    assert client.post(f"/extractions/{result['id']}/undo").status_code == 409


def test_the_same_file_read_again_waits_for_review(client, project, use_extractor):
    use_extractor(FakeExtractor({"terrain": COMPLETE["terrain"]}))
    file_id = upload(client, project)

    assert read(client, project, file_id).json()["status"] == "applied"
    assert read(client, project, file_id).json()["status"] == "review"
    assert len(terrains(client, project)) == 1


def test_deleting_the_file_forgets_what_was_read(client, project, use_extractor):
    use_extractor(FakeExtractor({"plan": {"level": found("1")}}))
    file_id = upload(client, project)
    read(client, project, file_id)

    assert client.delete(f"/files/{file_id}").status_code == 204

    [kept] = client.get(f"/projects/{project}/extractions").json()
    assert (kept["status"], kept["proposal"], kept["file_id"]) == ("failed", {}, None)


@pytest.mark.parametrize(
    "answer",
    [
        '{"terrain": {"area_m2": {"value": 1'
        + "0" * 400
        + ', "confidence": 1, "source": "p. 1"}}}',
        '{"plan": ' + "[" * 20000 + "]" * 20000 + "}",
        RuntimeError("unexpected"),
    ],
    ids=["huge-number", "deep-json", "unexpected-error"],
)
def test_a_broken_answer_fails_without_an_error(client, project, use_extractor, answer):
    use_extractor(FakeExtractor(answer))

    result = read(client, project)

    assert (result.status_code, result.json()["status"]) == (201, "failed")


@pytest.mark.parametrize("value", [0.001, 999.999999])
def test_a_number_the_column_cannot_keep_is_dropped(value):
    name = "area_m2" if value < 1 else "slope_percent"
    reading = read_proposal(json.dumps({"terrain": {name: found(value)}}))

    assert (reading.proposal, reading.sure) == ({}, False)


def test_text_that_cannot_be_stored_is_dropped():
    reading = read_proposal(json.dumps({"plan": {"title": found("Planta\x00baja")}}))

    assert reading.proposal == {}


def test_coordinates_never_enter_as_a_place():
    reading = read_proposal(json.dumps({"project": {"location": found("4.6097, -74.0817")}}))

    assert reading.proposal == {}


def test_a_rejected_section_sends_the_rest_to_review():
    answer = {"terrain": {"area_m2": found(-4)}, "plan": {"title": found("Planta")}}

    reading = read_proposal(json.dumps(answer))

    assert (list(reading.proposal), reading.sure) == (["plan"], False)


@pytest.mark.parametrize(
    ("name", "value", "source", "expected"),
    [
        ("area_m2", 500.0, "not stated; estimated from drawing", False),
        ("area_m2", 500.0, "Página 1: área 500", False),
        ("area_m2", 500.0, "Página 1: área estimada 500 m2", False),
        ("area_m2", 500.0, "área 500 m2", False),
        ("area_m2", 1250.5, "Página 2: área de 1.250,5 m²", True),
        ("width_m", 12.0, "page 1: frente 12 m", True),
        ("width_m", 12.0, "page 1: área 12 m2", False),
        ("width_m", 2.0, "page 1: frente 12 m", False),
        ("slope_percent", 6.0, "Página 1: pendiente 6 %", True),
        ("title", "Planta baja", "Página 1: PLANTA  BAJA", True),
        ("title", "Planta baja", "Página 1: corte A", False),
        ("area_m2", 250.0, "Página 1: área 1 250 m2", False),
        ("area_m2", 1250.0, "Página 1: área 1 250 m2", False),
        ("area_m2", 250.0, "Página 1: Lote 2 250 m2", False),
        ("area_m2", 2250.0, "Página 1: Lote 2 250 m2", False),
        ("area_m2", 250.0, "Página 1: área 1´250 m2", False),
        ("slope_percent", 5.0, "Página 1: pendiente \u20145 %", False),
        ("area_m2", 250.0, "Página 1: área 1'250 m2", False),
        ("area_m2", 250.0, "Página 1: área 1\u00a0250 m2", False),
        ("width_m", 120.0, "Página 1: 120 metros cuadrados", False),
        ("width_m", 120.0, "Página 1: 120 m^2", False),
        ("width_m", 120.0, "Página 1: 120 m 2", False),
        ("width_m", 120.0, "Página 1: 120 m²", False),
        ("slope_percent", 5.0, "Página 1: pendiente \u22125 %", False),
        ("width_m", 2500.0, "Página 1: ancho 2.500 m", False),
    ],
)
def test_only_a_quote_that_holds_the_value_supports_it(name, value, source, expected):
    assert is_supported(name, value, source) is expected


def encrypted_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("data", "pages"),
    [
        (PDF, 1),
        (make_pdf(200), 200),
        (b"%PDF-1.4\n<< /Type /Catalog >>", None),
        (b"%PDF-1.4\n" + b"<< /Type /Page >>\n" * 50, None),
        (b"%PDF-1.5\n<< /Type /ObjStm /Filter /FlateDecode >>\nstream\nbroken\nendstream", None),
    ],
    ids=["one", "two-hundred", "no-pages", "loose-objects", "broken-stream"],
)
def test_pages_are_counted_or_the_document_is_refused(data, pages):
    assert documents.count_pages(data) == pages


def test_an_encrypted_pdf_is_refused():
    assert documents.count_pages(encrypted_pdf()) is None


def test_a_flood_of_streams_is_refused_quickly():
    started = time.monotonic()

    assert documents.count_pages(b"%PDF-/ObjStm" + b"stream\n#41#41#41" * 200000) is None
    assert time.monotonic() - started < documents.PARSE_SECONDS + 1


def lying_pdf(pages):
    """A page tree that declares one page and holds many."""
    writer = PdfWriter()

    for _ in range(pages):
        writer.add_blank_page(width=10, height=10)

    writer._root_object["/Pages"].get_object()[NameObject("/Count")] = NumberObject(1)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_a_huge_page_tree_is_stopped_early_and_others_still_pass():
    started = time.monotonic()

    for _ in range(3):
        assert documents.count_pages(lying_pdf(3000)) == 11

    assert time.monotonic() - started < 3
    assert documents.count_pages(PDF) == 1


def test_ten_pages_pass_and_eleven_do_not():
    documents.check_document(make_pdf(10), "application/pdf")

    with pytest.raises(InvalidDataError):
        documents.check_document(make_pdf(11), "application/pdf")


def test_a_huge_image_is_refused(client, project, use_extractor):
    extractor = use_extractor(FakeExtractor())
    size = (50_000).to_bytes(4, "big") * 2
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + size + b"\x08\x02\x00\x00\x00"

    assert read(client, project, upload(client, project, png, "grande.png")).status_code == 422
    assert extractor.calls == 0


@pytest.mark.parametrize(
    ("url", "model", "external"),
    [
        ("http://127.0.0.1:11434", "vision", False),
        ("http://localhost:11434", "vision", False),
        ("https://gpu.example.com", "vision", True),
        ("http://127.0.0.1:11434", "vision:cloud", True),
        ("http://127.0.0.1:11434", "vision-cloud", True),
        ("http://[broken", "vision", True),
    ],
)
def test_consent_is_needed_whenever_the_document_leaves_the_machine(url, model, external):
    assert providers.OllamaExtractor(url, model).external is external


def test_one_reading_at_a_time_per_user_and_a_few_in_total(monkeypatch):
    monkeypatch.setattr(capacity, "MAX_AT_ONCE", 1)

    with capacity.reading_slot(1):
        for user in (1, 2):
            with pytest.raises(TooManyAttemptsError), capacity.reading_slot(user):
                pass

    with capacity.reading_slot(2):
        pass


def test_the_global_daily_limit(client, project, use_extractor, monkeypatch):
    monkeypatch.setenv("AI_EXTRACTION_DAILY_LIMIT", "1")
    use_extractor(FakeExtractor({}))

    assert read(client, project).status_code == 201
    assert read(client, project).status_code == 429


@pytest.mark.parametrize(
    "body",
    [
        {"project": {}},
        {"terrain": {"name": "Lote", "area_m2": 100, "latitude": 4.6}},
        {"plan": {"title": "Planta", "file_id": 1}},
        {"plan": {"title": "Planta\x00"}},
    ],
)
def test_a_review_takes_only_what_it_saves(client, project, use_extractor, body):
    use_extractor(FakeExtractor({"plan": {"level": found("1")}}))
    extraction = read(client, project).json()["id"]

    assert client.post(f"/extractions/{extraction}/apply", json=body).status_code == 422


def test_times_are_sent_in_utc(client, project, use_extractor):
    use_extractor(FakeExtractor({}))

    assert read(client, project).json()["created_at"].endswith("Z")


def test_consent_must_be_a_real_boolean(client, project, use_extractor):
    use_extractor(FakeExtractor())

    assert read(client, project, consent="yes").status_code == 422
