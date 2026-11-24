import json
import os
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import storage
from app.errors import (
    ConflictError,
    FileTooLargeError,
    InvalidDataError,
    NotConfiguredError,
    NotFoundError,
    TooManyAttemptsError,
    UnsupportedFileError,
)
from app.extraction.capacity import reading_slot
from app.extraction.documents import check_document
from app.extraction.proposal import Reading, read_proposal
from app.extraction.providers import Extractor
from app.extraction.schemas import ExtractionApply, ExtractionRead
from app.logs import logger
from app.models import AIExtraction, File, Plan, Project, Terrain, User
from app.services.base import ProjectScopedService
from app.services.file_service import FileService
from app.services.state_store import utc_now

# Under the 4.5 MB of a Vercel request, with room for the multipart envelope.
MAX_DOCUMENT_BYTES = 4_300_000
MAX_PER_DAY = 10
DEFAULT_GLOBAL_PER_DAY = 100

TERRAIN_FIELDS = ("name", "area_m2", "width_m", "length_m", "slope_percent", "soil_type")
PLAN_FIELDS = ("title", "level", "scale")
CHANGED_AFTERWARDS = "It changed after the document was applied"
# A building proposal (R13) shares the table, the quota and the consent: no migration is needed.
BUILD_MARK = '{"build"'


def is_build(extraction: AIExtraction) -> bool:
    return extraction.proposal is not None and extraction.proposal.startswith(BUILD_MARK)


def global_daily_limit() -> int:
    try:
        return int(os.environ["AI_EXTRACTION_DAILY_LIMIT"])
    except (KeyError, ValueError):
        return DEFAULT_GLOBAL_PER_DAY


def _comparable(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value

    return round(float(value), 2)


def comparable_state(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: _comparable(getattr(item, name)) for name in fields}


def to_read(extraction: AIExtraction) -> ExtractionRead:
    # Its project was deleted while the request ran.
    if extraction.project_id is None:
        raise NotFoundError("Extraction not found")

    snapshot = json.loads(extraction.snapshot) if extraction.snapshot else {}

    return ExtractionRead(
        id=extraction.id,
        project_id=extraction.project_id,
        file_id=extraction.file_id,
        status=extraction.status,
        proposal=json.loads(extraction.proposal) if extraction.proposal else {},
        terrain_id=snapshot.get("terrain", {}).get("id"),
        plan_id=snapshot.get("plan", {}).get("id"),
        project_fields=sorted(snapshot.get("project", {})),
        created_at=extraction.created_at,
    )


class ExtractionService(ProjectScopedService):
    """A row is "failed" until its answer is stored, so nothing can apply a reading in progress."""

    def __init__(self, session: Session, user: User) -> None:
        super().__init__(session, user)
        self.files = FileService(session, user)

    def list(self, project_id: int) -> list[AIExtraction]:
        self._ensure_project_exists(project_id)

        return list(
            self.session.scalars(
                select(AIExtraction)
                .where(
                    AIExtraction.project_id == project_id,
                    or_(
                        AIExtraction.proposal.is_(None),
                        ~AIExtraction.proposal.startswith(BUILD_MARK, autoescape=True),
                    ),
                )
                .order_by(AIExtraction.id.desc())
                .limit(20)
            )
        )

    def create(
        self, project_id: int, file_id: int, consent: bool, extractor: Extractor | None
    ) -> AIExtraction:
        self._ensure_project_exists(project_id)
        file = self.files.get(file_id)

        if file.project_id != project_id:
            raise NotFoundError("File not found in this project")

        if extractor is None:
            raise NotConfiguredError("Document reading is not configured")

        if extractor.external and not consent:
            raise InvalidDataError("Consent is needed to send the document to an external service")

        if file.mime_type not in extractor.mime_types:
            raise UnsupportedFileError("The document reader does not support this type of file")

        if file.size_bytes > MAX_DOCUMENT_BYTES:
            raise FileTooLargeError("The document exceeds the 4.3 MB limit for reading")

        with reading_slot(self.user.id):
            data = self._content(file)
            mime_type = file.mime_type
            check_document(data, mime_type)

            extraction_id = self._reserve(project_id, file.id)
            # No connection or lock is held while the provider works.
            self.session.commit()

            try:
                reading = read_proposal(extractor.extract(data, mime_type))
            except Exception as error:
                # Only the kind of error: the document and the answer are personal data.
                logger.warning("extraction_failed", extra={"reason": type(error).__name__})
                return self._get(extraction_id)

        try:
            return self._finish(extraction_id, reading)
        except SQLAlchemyError as error:
            self.session.rollback()
            logger.warning("extraction_not_saved", extra={"reason": type(error).__name__})
            return self._get(extraction_id)

    def apply(self, extraction_id: int, data: ExtractionApply) -> AIExtraction:
        extraction = self._get(extraction_id, lock=True)

        if extraction.status != "review" or extraction.proposal is None:
            raise ConflictError("This proposal is not waiting for review")

        self._apply(extraction, data)
        self.session.commit()
        self.session.refresh(extraction)

        return extraction

    def undo(self, extraction_id: int) -> AIExtraction:
        extraction = self._get(extraction_id, lock=True)

        if extraction.status != "applied":
            raise ConflictError("There is nothing to undo")

        snapshot = json.loads(extraction.snapshot or "{}")
        project = self._locked(Project, extraction.project_id)
        created = []

        for key, model, fields in (
            ("terrain", Terrain, TERRAIN_FIELDS),
            ("plan", Plan, PLAN_FIELDS),
        ):
            if key not in snapshot:
                continue

            item = self._locked(model, snapshot[key]["id"])

            # Deleted, and perhaps restored with another id: it cannot be told apart any more.
            if item is None or project is None or item.project_id != project.id:
                raise ConflictError(CHANGED_AFTERWARDS)

            if comparable_state(item, fields) != snapshot[key]["values"]:
                raise ConflictError(CHANGED_AFTERWARDS)

            # Deleting these would take the user's later work with them.
            if key == "terrain" and (
                item.points or item.latitude is not None or item.longitude is not None
            ):
                raise ConflictError(CHANGED_AFTERWARDS)

            if key == "plan" and (
                item.rooms
                or item.components
                or item.surface is not None
                or item.file_id != extraction.file_id
            ):
                raise ConflictError(CHANGED_AFTERWARDS)

            created.append(item)

        changes = snapshot.get("project", {})

        for name, change in changes.items():
            if project is None or getattr(project, name) != change["after"]:
                raise ConflictError(CHANGED_AFTERWARDS)

        for name, change in changes.items():
            setattr(project, name, change["before"])

        for item in created:
            self.session.delete(item)

        extraction.status = "undone"
        self.session.commit()
        self.session.refresh(extraction)

        return extraction

    def _finish(self, extraction_id: int, reading: Reading) -> AIExtraction:
        extraction = self._get(extraction_id, lock=True)

        # No file: it was deleted during the reading, and what was read goes with it.
        if not reading.proposal or extraction.proposal is not None or extraction.file_id is None:
            self.session.commit()
            return extraction

        values = {
            section: {name: field.value for name, field in fields.items()}
            for section, fields in reading.proposal.items()
        }
        extraction.proposal = json.dumps(
            {
                section: {name: field.model_dump() for name, field in fields.items()}
                for section, fields in reading.proposal.items()
            }
        )
        extraction.status = "review"
        self.session.flush()

        if reading.sure and not self._was_applied(extraction):
            project = self._locked(Project, extraction.project_id)
            wanted = values.get("project", {})

            # What the user wrote is never replaced without asking.
            if project is not None and not any(getattr(project, name) for name in wanted):
                try:
                    data = ExtractionApply.model_validate(values)
                except ValueError:
                    data = None

                if data is not None:
                    self._apply(extraction, data)

        self.session.commit()
        self.session.refresh(extraction)

        return extraction

    def _apply(self, extraction: AIExtraction, data: ExtractionApply) -> None:
        """Everything or nothing: the caller commits once."""
        snapshot: dict[str, Any] = {}

        if data.project is not None:
            project = self._locked(Project, extraction.project_id)

            if project is None:
                raise NotFoundError("Project not found")

            changes = {
                name: {"before": getattr(project, name), "after": value}
                for name, value in data.project.model_dump(exclude_none=True).items()
                if getattr(project, name) != value
            }

            for name, change in changes.items():
                setattr(project, name, change["after"])

            if changes:
                snapshot["project"] = changes

        if data.terrain is not None:
            terrain = Terrain(project_id=extraction.project_id, **data.terrain.model_dump())
            self.session.add(terrain)
            self.session.flush()
            self.session.refresh(terrain)
            snapshot["terrain"] = {
                "id": terrain.id,
                "values": comparable_state(terrain, TERRAIN_FIELDS),
            }

        if data.plan is not None:
            plan = Plan(
                project_id=extraction.project_id,
                file_id=extraction.file_id,
                **data.plan.model_dump(),
            )
            self.session.add(plan)
            self.session.flush()
            snapshot["plan"] = {"id": plan.id, "values": comparable_state(plan, PLAN_FIELDS)}

        extraction.snapshot = json.dumps(snapshot)
        extraction.status = "applied"

    def _was_applied(self, extraction: AIExtraction) -> bool:
        """The same file read again waits for review: it would fill everything in twice."""
        if extraction.file_id is None:
            return False

        earlier = self.session.scalar(
            select(AIExtraction.id)
            .where(
                AIExtraction.file_id == extraction.file_id,
                AIExtraction.status == "applied",
            )
            .limit(1)
        )

        return earlier is not None

    def _reserve(self, project_id: int, file_id: int | None, proposal: str | None = None) -> int:
        # The user row is locked so that two requests cannot both take the last reading.
        self.session.scalar(
            select(User.id).where(User.id == self.user.id).with_for_update(key_share=True)
        )
        since = AIExtraction.created_at >= utc_now() - timedelta(days=1)
        count = select(func.count()).select_from(AIExtraction).where(since)

        if self.session.scalar(count.where(AIExtraction.user_id == self.user.id)) >= MAX_PER_DAY:
            raise TooManyAttemptsError("The daily limit of documents was reached")

        if self.session.scalar(count) >= global_daily_limit():
            raise TooManyAttemptsError("The daily limit of the document reader was reached")

        extraction = AIExtraction(
            project_id=project_id,
            file_id=file_id,
            user_id=self.user.id,
            status="failed",
            proposal=proposal,
            created_at=utc_now(),
        )
        self.session.add(extraction)
        self.session.flush()

        return extraction.id

    def _locked(self, model: type, item_id: int | None) -> Any:
        if item_id is None:
            return None

        # populate_existing: without it the lock returns the values loaded before waiting for it.
        return self.session.get(model, item_id, with_for_update=True, populate_existing=True)

    def _get(self, extraction_id: int, lock: bool = False, build: bool = False) -> AIExtraction:
        extraction = self.session.get(
            AIExtraction, extraction_id, with_for_update=lock, populate_existing=True
        )

        if (
            extraction is None
            or extraction.project_id is None
            or is_build(extraction) != build
            or not self._owns(extraction.project_id)
        ):
            raise NotFoundError("Extraction not found")

        return extraction

    def _content(self, file: File) -> bytes:
        data = self.files.content_data(file)

        if data is None:
            data = self.files.content_path(file).read_bytes()

        if storage.detect_type(data[:16]) is None:
            raise UnsupportedFileError("The file content is not a supported document")

        return data
