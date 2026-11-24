"""The AI project builder (R13): the AI proposes, the user completes and confirms, nothing else."""

import json
import math
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
from app.extraction.proposal import ProposedField
from app.extraction.providers import Extractor
from app.extraction.schemas import (
    BuildApply,
    BuildCreate,
    BuildProposal,
    BuildRead,
    BuildRecommendation,
)
from app.limits import MAX_TEXT_LENGTH
from app.logs import logger
from app.models import (
    AIExtraction,
    Plan,
    Project,
    Recommendation,
    Room,
    StructuralComponent,
    Terrain,
    TerrainPoint,
)
from app.schemas import ComponentCreate, PlanCreate, RoomCreate
from app.services.auto_layout import complete_geometry, from_description, lot_dimensions
from app.services.extraction_service import (
    BUILD_MARK,
    CHANGED_AFTERWARDS,
    MAX_DOCUMENT_BYTES,
    PLAN_FIELDS,
    ExtractionService,
    comparable_state,
    is_build,
)
from app.services.recommendation_rules import terrain_suggestions

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
PROJECT_BUILD_FIELDS = ("name", "description", "location")
TERRAIN_BUILD_FIELDS = (
    "name",
    "area_m2",
    "width_m",
    "length_m",
    "slope_percent",
    "soil_type",
)
RECOMMENDATION_STATE = ("category", "content", "source", "priority")


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
        fallback=proposal.fallback,
        levels=proposal.levels,
        project=proposal.project,
        terrain=proposal.terrain,
        recommendations=proposal.recommendations,
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

        if extractor is None and data.description is None:
            raise NotConfiguredError("Document reading is not configured")

        if extractor is not None and extractor.external and not data.consent:
            raise InvalidDataError("Consent is needed to send the document to an external service")

        if (
            file is not None
            and extractor is not None
            and file.mime_type not in extractor.mime_types
        ):
            raise UnsupportedFileError("The document reader does not support this type of file")

        if file is not None and extractor is not None and file.size_bytes > MAX_DOCUMENT_BYTES:
            raise FileTooLargeError("The document exceeds the 4.3 MB limit for reading")

        # A combined request sends the file only when a configured provider can read it.
        # Without one, the local text fallback only uses the explicitly supplied description.
        reads_document = file is not None and extractor is not None
        origin = "document" if reads_document else "description"
        pending = json.dumps({"build": BuildProposal(origin=origin).model_dump()})

        with reading_slot(self.user.id):
            document = None

            if reads_document:
                content = self._content(file)
                check_document(content, file.mime_type)
                document = (content, file.mime_type)

            build_id = self._reserve(project_id, data.file_id, pending)
            # No connection or lock is held while the provider works.
            self.session.commit()

            try:
                if extractor is None:
                    proposal = from_description(data.description or "")
                else:
                    answer = extractor.read(
                        BUILD_INSTRUCTIONS,
                        _request(data.description),
                        document,
                        MAX_BUILD_OUTPUT_TOKENS,
                    )
                    proposal = read_build(answer, origin, data.description)
                proposal = self._complete_context(project_id, proposal, data.description)
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

    def _complete_context(
        self, project_id: int, proposal: BuildProposal, description: str | None
    ) -> BuildProposal:
        project = self.session.get(Project, project_id)
        terrain = self.session.scalar(
            select(Terrain).where(Terrain.project_id == project_id).order_by(Terrain.id.desc())
        )
        project_values = (
            {
                name: getattr(project, name)
                for name in ("name", "description", "location")
                if getattr(project, name) is not None
            }
            if project is not None
            else {}
        )
        terrain_values = (
            {
                name: getattr(terrain, name)
                for name in (
                    "name",
                    "area_m2",
                    "width_m",
                    "length_m",
                    "slope_percent",
                    "soil_type",
                )
                if getattr(terrain, name) is not None
            }
            if terrain is not None
            else {}
        )
        for name, value in project_values.items():
            source = str(value)
            if name not in proposal.project and len(source) <= 200:
                proposal.project[name] = ProposedField(
                    value=value, confidence=1.0, source=source, origin="existing"
                )

        outline_width = outline_length = None
        if terrain is not None and len(terrain.points) >= 3:
            xs = [float(point.x_m) for point in terrain.points]
            ys = [float(point.y_m) for point in terrain.points]
            outline_width = max(xs) - min(xs)
            outline_length = max(ys) - min(ys)

            if terrain.width_m is None and "width_m" not in proposal.terrain and outline_width > 0:
                proposal.terrain["width_m"] = ProposedField(
                    value=outline_width,
                    confidence=0.0,
                    source="",
                    origin="ai_generated",
                )
            if (
                terrain.length_m is None
                and "length_m" not in proposal.terrain
                and outline_length > 0
            ):
                proposal.terrain["length_m"] = ProposedField(
                    value=outline_length,
                    confidence=0.0,
                    source="",
                    origin="ai_generated",
                )

        for name, value in terrain_values.items():
            if name not in proposal.terrain:
                proposal.terrain[name] = ProposedField(
                    value=(
                        float(value)
                        if name.endswith("_m2") or name.endswith("_m") or name == "slope_percent"
                        else value
                    ),
                    confidence=1.0,
                    source=str(value),
                    origin="existing",
                )

        text_width, text_length = lot_dimensions(description or "")

        def dimension(name: str, actual: Any) -> float | None:
            if actual is not None:
                return float(actual)

            field = proposal.terrain.get(name)
            if field is None or isinstance(field.value, bool):
                return None

            try:
                value = float(field.value)
            except (TypeError, ValueError):
                return None

            return value if math.isfinite(value) and value > 0 else None

        lot_width = dimension(
            "width_m", terrain.width_m if terrain is not None else outline_width or text_width
        )
        lot_length = dimension(
            "length_m",
            terrain.length_m if terrain is not None else outline_length or text_length,
        )

        if lot_width is None:
            lot_width = 10.0
        if lot_length is None:
            lot_length = 20.0
        proposal.terrain.setdefault(
            "width_m",
            ProposedField(value=lot_width, confidence=0.0, source="", origin="ai_generated"),
        )
        proposal.terrain.setdefault(
            "length_m",
            ProposedField(value=lot_length, confidence=0.0, source="", origin="ai_generated"),
        )

        proposal.terrain.setdefault(
            "name",
            ProposedField(
                value="Terreno principal",
                confidence=0.0,
                source="",
                origin="ai_generated",
            ),
        )
        proposal.terrain.setdefault(
            "area_m2",
            ProposedField(
                value=round(lot_width * lot_length, 2),
                confidence=0.0,
                source="",
                origin="ai_generated",
            ),
        )
        proposal = complete_geometry(proposal, lot_width, lot_length)
        terrain_name = str(proposal.terrain["name"].value)
        slope = proposal.terrain.get("slope_percent")
        soil = proposal.terrain.get("soil_type")
        terrain_for_rules = Terrain(
            name=terrain_name,
            area_m2=proposal.terrain["area_m2"].value,
            slope_percent=slope.value if slope else None,
            soil_type=soil.value if soil else None,
        )
        proposal.recommendations = [
            BuildRecommendation(
                category=category,
                content=_recommendation_text(content),
                priority=priority,
            )
            for category, content, priority in terrain_suggestions([terrain_for_rules])
        ]

        return proposal

    def apply_build(self, build_id: int, data: BuildApply) -> AIExtraction:
        """The accepted project context and building are saved in one transaction."""
        build = self._get(build_id, lock=True, build=True)

        if build.status != "review":
            raise ConflictError("This proposal is not waiting for review")

        project = self._locked(Project, build.project_id)

        if project is None:
            raise NotFoundError("Project not found")

        snapshot: dict[str, Any] = {}
        project_changes = {
            name: {"before": getattr(project, name), "after": value}
            for name, value in (
                data.project.model_dump(exclude_none=True, exclude_unset=True).items()
                if data.project is not None
                else ()
            )
            if getattr(project, name) != value
        }

        for name, change in project_changes.items():
            setattr(project, name, change["after"])

        if project_changes:
            snapshot["project"] = project_changes

        if data.terrain is not None:
            terrain_values = data.terrain.model_dump(exclude_none=True, exclude_unset=True)
            terrain = self.session.scalar(
                select(Terrain)
                .where(Terrain.project_id == project.id)
                .order_by(Terrain.id.desc())
                .with_for_update()
            )

            if terrain is None:
                terrain = Terrain(project_id=project.id, **data.terrain.model_dump())
                if terrain.width_m is not None and terrain.length_m is not None:
                    width, length = float(terrain.width_m), float(terrain.length_m)
                    terrain.points = [
                        TerrainPoint(position=position, x_m=x, y_m=y)
                        for position, (x, y) in enumerate(
                            ((0, 0), (width, 0), (width, length), (0, length))
                        )
                    ]
                self.session.add(terrain)
                self.session.flush()
                self.session.refresh(terrain)
                snapshot["terrain"] = {
                    "id": terrain.id,
                    "created": True,
                    "values": comparable_state(terrain, TERRAIN_BUILD_FIELDS),
                    "points": _terrain_points(terrain),
                }
            else:
                before = comparable_state(terrain, TERRAIN_BUILD_FIELDS)
                for name, value in terrain_values.items():
                    setattr(terrain, name, value)
                self.session.flush()
                snapshot["terrain"] = {
                    "id": terrain.id,
                    "created": False,
                    "before": before,
                    "values": comparable_state(terrain, TERRAIN_BUILD_FIELDS),
                }

        proposal = _proposal(build)
        saved_recommendations = []
        for suggestion in proposal.recommendations:
            duplicate = self.session.scalar(
                select(Recommendation.id).where(
                    Recommendation.project_id == project.id,
                    Recommendation.source == "system",
                    Recommendation.category == suggestion.category,
                    Recommendation.content == suggestion.content,
                )
            )
            if duplicate is not None:
                continue
            recommendation = Recommendation(
                project_id=project.id,
                category=suggestion.category,
                content=suggestion.content,
                source="system",
                priority=suggestion.priority,
            )
            self.session.add(recommendation)
            saved_recommendations.append(recommendation)

        self.session.flush()
        if saved_recommendations:
            snapshot["recommendations"] = [
                {
                    "id": recommendation.id,
                    "values": comparable_state(recommendation, RECOMMENDATION_STATE),
                }
                for recommendation in saved_recommendations
            ]

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

        snapshot["plans"] = [
            {
                "id": plan.id,
                "values": comparable_state(plan, PLAN_FIELDS),
                "rooms": [_entry(room, ROOM_STATE) for room in rooms],
                "components": [_entry(item, COMPONENT_STATE) for item in components],
            }
            for plan, rooms, components in plans
        ]
        build.snapshot = json.dumps(snapshot)
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
        terrain_to_delete = None
        terrain_to_restore = None
        recommendations_to_delete = []

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

        for name, change in snapshot.get("project", {}).items():
            if project is None or getattr(project, name) != change["after"]:
                raise ConflictError(CHANGED_AFTERWARDS)

        terrain_entry = snapshot.get("terrain")
        if terrain_entry is not None:
            terrain = self._locked(Terrain, terrain_entry["id"])
            if terrain is None or project is None or terrain.project_id != project.id:
                raise ConflictError(CHANGED_AFTERWARDS)
            if comparable_state(terrain, TERRAIN_BUILD_FIELDS) != terrain_entry["values"]:
                raise ConflictError(CHANGED_AFTERWARDS)
            if terrain_entry["created"]:
                if (
                    _terrain_points(terrain) != terrain_entry["points"]
                    or terrain.latitude is not None
                    or terrain.longitude is not None
                ):
                    raise ConflictError(CHANGED_AFTERWARDS)
                terrain_to_delete = terrain
            else:
                terrain_to_restore = (terrain, terrain_entry["before"])

        for entry in snapshot.get("recommendations", []):
            recommendation = self._locked(Recommendation, entry["id"])
            if (
                recommendation is None
                or recommendation.project_id != build.project_id
                or comparable_state(recommendation, RECOMMENDATION_STATE) != entry["values"]
            ):
                raise ConflictError(CHANGED_AFTERWARDS)
            recommendations_to_delete.append(recommendation)

        for name, change in snapshot.get("project", {}).items():
            setattr(project, name, change["before"])
        if terrain_to_restore is not None:
            terrain, before = terrain_to_restore
            for name, value in before.items():
                setattr(terrain, name, value)

        for plan in plans:
            self.session.delete(plan)
        if terrain_to_delete is not None:
            self.session.delete(terrain_to_delete)
        for recommendation in recommendations_to_delete:
            self.session.delete(recommendation)

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


def _terrain_points(terrain: Terrain) -> list[dict[str, Any]]:
    return [
        {
            "position": point.position,
            "x_m": round(float(point.x_m), 2),
            "y_m": round(float(point.y_m), 2),
        }
        for point in terrain.points
    ]


def _recommendation_text(content: str) -> str:
    if len(content) <= MAX_TEXT_LENGTH:
        return content

    shortened = content[: MAX_TEXT_LENGTH - 1].rsplit(" ", 1)[0].rstrip()
    return shortened + "…"
