"""The AI project builder (R13): the AI proposes, the user completes and confirms, nothing else."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.errors import (
    ConflictError,
    FileTooLargeError,
    InvalidDataError,
    NotConfiguredError,
    NotFoundError,
    UnsupportedFileError,
)
from app.extraction.builder import BUILD_INSTRUCTIONS, MAX_BUILD_OUTPUT_TOKENS, read_build
from app.extraction.capacity import reading_slot
from app.extraction.documents import check_document
from app.extraction.providers import Extractor
from app.extraction.schemas import BuildApply, BuildCreate, BuildProposal, BuildRead
from app.logs import logger
from app.models import AIExtraction, Plan, Project, Room, StructuralComponent
from app.schemas import ComponentCreate, PlanCreate, RoomCreate
from app.services.extraction_service import (
    BUILD_MARK,
    CHANGED_AFTERWARDS,
    MAX_DOCUMENT_BYTES,
    PLAN_FIELDS,
    ExtractionService,
    comparable_state,
    is_build,
)

ROOM_STATE = (
    "plan_id",
    "unit_id",
    "name",
    "category",
    "mesh_ref",
    "x_m",
    "y_m",
    "width_m",
    "depth_m",
    "height_m",
    "surface",
)
COMPONENT_STATE = (
    "plan_id",
    "kind",
    "name",
    "x_m",
    "y_m",
    "width_m",
    "depth_m",
    "height_m",
    "surface",
)


def _proposal(extraction: AIExtraction) -> BuildProposal:
    return BuildProposal.model_validate(json.loads(extraction.proposal or "{}")["build"])


def to_build_read(extraction: AIExtraction) -> BuildRead:
    if extraction.project_id is None or not is_build(extraction):
        raise NotFoundError("Build not found")

    proposal = _proposal(extraction)
    snapshot = json.loads(extraction.snapshot) if extraction.snapshot else {}

    return BuildRead(
        id=extraction.id,
        project_id=extraction.project_id,
        file_id=extraction.file_id,
        status=extraction.status,
        origin=proposal.origin,
        levels=proposal.levels,
        truncated=proposal.truncated,
        plan_ids=[plan["id"] for plan in snapshot.get("plans", [])],
        created_at=extraction.created_at,
    )


def _request(description: str | None) -> str:
    if description is None:
        return "Read this document."

    # The description is data: it is fenced so that it cannot pass for an instruction.
    return f"Read this description of a building.\n<description>\n{description}\n</description>"


class BuildService(ExtractionService):
    def list_builds(self, project_id: int) -> list[AIExtraction]:
        self._ensure_project_exists(project_id)
        return list(
            self.session.scalars(
                select(AIExtraction)
                .where(
                    AIExtraction.project_id == project_id,
                    AIExtraction.proposal.startswith(BUILD_MARK, autoescape=True),
                )
                .order_by(AIExtraction.id.desc())
                .limit(20)
            )
        )

    def create_build(
        self, project_id: int, data: BuildCreate, extractor: Extractor | None
    ) -> AIExtraction:
        self._ensure_project_exists(project_id)
        file = None

        if data.file_id is not None:
            file = self.files.get(data.file_id)

            if file.project_id != project_id:
                raise NotFoundError("File not found in this project")

        if extractor is None:
            raise NotConfiguredError("Document reading is not configured")

        if extractor.external and not data.consent:
            raise InvalidDataError("Consent is needed to send the document to an external service")

        if file is not None and file.mime_type not in extractor.mime_types:
            raise UnsupportedFileError("The document reader does not support this type of file")

        if file is not None and file.size_bytes > MAX_DOCUMENT_BYTES:
            raise FileTooLargeError("The document exceeds the 4.3 MB limit for reading")

        origin = "description" if file is None else "document"
        pending = json.dumps({"build": BuildProposal(origin=origin).model_dump()})

        with reading_slot(self.user.id):
            document = None

            if file is not None:
                content = self._content(file)
                check_document(content, file.mime_type)
                document = (content, file.mime_type)

            build_id = self._reserve(project_id, data.file_id, pending)
            # No connection or lock is held while the provider works.
            self.session.commit()

            try:
                answer = extractor.read(
                    BUILD_INSTRUCTIONS,
                    _request(data.description),
                    document,
                    MAX_BUILD_OUTPUT_TOKENS,
                )
                proposal = read_build(answer, origin, data.description)
            except Exception as error:
                # Only the kind of error: the description, the document and the answer are private.
                logger.warning("build_failed", extra={"reason": type(error).__name__})
                return self._get(build_id, build=True)

        try:
            return self._finish_build(build_id, proposal)
        except SQLAlchemyError as error:
            self.session.rollback()
            logger.warning("build_not_saved", extra={"reason": type(error).__name__})
            return self._get(build_id, build=True)

    def apply_build(self, build_id: int, data: BuildApply) -> AIExtraction:
        """Every level, room and component in one transaction, or nothing."""
        build = self._get(build_id, lock=True, build=True)

        if build.status != "review":
            raise ConflictError("This proposal is not waiting for review")

        project = self._locked(Project, build.project_id)

        if project is None:
            raise NotFoundError("Project not found")

        plans = []

        for level in data.levels:
            # The same validation as the forms: an AI proposal has no shortcut.
            plan_data = PlanCreate(
                file_id=build.file_id, title=level.title, level=level.level, scale=level.scale
            )
            plan = Plan(project_id=project.id, **plan_data.model_dump())
            self.session.add(plan)
            self.session.flush()
            rooms = [
                Room(
                    project_id=project.id,
                    **RoomCreate(plan_id=plan.id, **room.model_dump()).model_dump(),
                )
                for room in level.rooms
            ]
            components = [
                StructuralComponent(
                    project_id=project.id,
                    **ComponentCreate(plan_id=plan.id, **component.model_dump()).model_dump(),
                )
                for component in level.components
            ]
            self.session.add_all([*rooms, *components])
            plans.append((plan, rooms, components))

        self.session.flush()

        for plan, rooms, components in plans:
            self.session.refresh(plan)

            for item in (*rooms, *components):
                self.session.refresh(item)

        build.snapshot = json.dumps(
            {
                "plans": [
                    {
                        "id": plan.id,
                        "values": comparable_state(plan, PLAN_FIELDS),
                        "rooms": [_entry(room, ROOM_STATE) for room in rooms],
                        "components": [_entry(item, COMPONENT_STATE) for item in components],
                    }
                    for plan, rooms, components in plans
                ]
            }
        )
        build.status = "applied"
        self.session.commit()
        self.session.refresh(build)

        return build

    def undo_build(self, build_id: int) -> AIExtraction:
        """Removes what was built, only while nobody changed it or built on it."""
        build = self._get(build_id, lock=True, build=True)

        if build.status != "applied":
            raise ConflictError("There is nothing to undo")

        project = self._locked(Project, build.project_id)
        snapshot = json.loads(build.snapshot or "{}")
        plans = []

        for entry in snapshot.get("plans", []):
            plan = self._locked(Plan, entry["id"])

            if (
                project is None
                or plan is None
                or plan.project_id != project.id
                or plan.file_id != build.file_id
                or plan.surface is not None
                or comparable_state(plan, PLAN_FIELDS) != entry["values"]
            ):
                raise ConflictError(CHANGED_AFTERWARDS)

            rooms = self._locked_children(Room, plan.id)
            components = self._locked_children(StructuralComponent, plan.id)

            if [_entry(room, ROOM_STATE) for room in rooms] != entry["rooms"] or [
                _entry(item, COMPONENT_STATE) for item in components
            ] != entry["components"]:
                raise ConflictError(CHANGED_AFTERWARDS)

            if any(
                room.spatial_elements or room.walkthrough_steps or room.renovation_logs
                for room in rooms
            ):
                raise ConflictError(CHANGED_AFTERWARDS)

            plans.append(plan)

        for plan in plans:
            self.session.delete(plan)

        build.status = "undone"
        self.session.commit()
        self.session.refresh(build)

        return build

    def _finish_build(self, build_id: int, proposal: BuildProposal) -> AIExtraction:
        build = self._get(build_id, lock=True, build=True)

        # A document deleted during the reading takes what was read with it.
        if (
            not proposal.levels
            or build.status != "failed"
            or (proposal.origin == "document" and build.file_id is None)
        ):
            self.session.commit()
            return build

        # Never applied on its own: the user always reviews and completes a building.
        build.proposal = json.dumps({"build": proposal.model_dump()})
        build.status = "review"
        self.session.commit()
        self.session.refresh(build)

        return build

    def _locked_children(self, model: type, plan_id: int) -> list[Any]:
        return list(
            self.session.scalars(
                select(model)
                .where(model.plan_id == plan_id)
                .order_by(model.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )


def _entry(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {"id": item.id, "values": comparable_state(item, fields)}
