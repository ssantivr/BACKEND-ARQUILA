import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import dtos, schemas
from app.models import Project
from app.services.file_service import clean_filename
from app.services.project_templates import TEMPLATES
from tests.helpers import register

FIELDS = [
    (schemas.ProjectCreate, "description"),
    (schemas.ProjectCreate, "location"),
    (schemas.RecommendationCreate, "content"),
]


@pytest.mark.parametrize(("schema", "field"), FIELDS)
def test_free_texts_take_200_characters_and_not_201(schema, field):
    values = {"name": "Casa", "category": "general"}

    schema(**{**values, field: "x" * 200})

    with pytest.raises(ValidationError):
        schema(**{**values, field: "x" * 201})


def test_no_typed_text_of_the_v1_api_is_longer_than_200():
    typed = []

    for model in vars(dtos).values():
        if not isinstance(model, type) or not hasattr(model, "model_fields"):
            continue

        for name in ("description", "address"):
            field = model.model_fields.get(name)
            limits = [getattr(m, "max_length", None) for m in field.metadata] if field else []
            typed += [limit for limit in limits if limit is not None]

    assert typed
    assert max(typed) == 200


def test_a_long_file_name_keeps_its_extension():
    name = clean_filename("a" * 300 + ".pdf")

    assert len(name) == 200
    assert name.endswith(".pdf")


@pytest.mark.parametrize("field", ["description", "location"])
def test_a_changed_text_has_the_limit(client, field):
    register(client)
    url = f"/projects/{client.post('/projects', json={'name': 'Casa'}).json()['id']}"

    assert client.patch(url, json={field: "x" * 200}).status_code == 200
    assert client.patch(url, json={field: "x" * 201}).status_code == 422


def test_an_older_long_text_does_not_block_a_rename(client, engine):
    register(client)
    project = client.post("/projects", json={"name": "Casa"}).json()["id"]
    old = "x" * 300

    with Session(engine) as session:
        session.get(Project, project).description = old
        session.commit()

    sent = {"name": "Casa norte", "description": old}

    assert client.patch(f"/projects/{project}", json=sent).status_code == 200


def test_a_long_search_is_rejected(client):
    register(client)

    assert client.get("/projects", params={"search": "x" * 201}).status_code == 422


def test_the_templates_respect_the_limit():
    templates = TEMPLATES.values() if isinstance(TEMPLATES, dict) else TEMPLATES

    assert all(len(template.description) <= 200 for template in templates)
