from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_session
from app.extraction.providers import Extractor, get_extractor
from app.extraction.schemas import (
    ExtractionApply,
    ExtractionAvailability,
    ExtractionCreate,
    ExtractionRead,
)
from app.models import User
from app.services.extraction_service import MAX_DOCUMENT_BYTES, ExtractionService, to_read

router = APIRouter(tags=["extractions"])


def get_service(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ExtractionService:
    return ExtractionService(session, user)


@router.get("/extraction/status", response_model=ExtractionAvailability)
def get_availability(
    user: User = Depends(get_current_user),
    extractor: Extractor | None = Depends(get_extractor),
):
    return ExtractionAvailability(
        available=extractor is not None,
        external=extractor is not None and extractor.external,
        mime_types=list(extractor.mime_types) if extractor else [],
        max_bytes=MAX_DOCUMENT_BYTES,
    )


@router.post(
    "/projects/{project_id}/extractions",
    response_model=ExtractionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_extraction(
    project_id: int,
    data: ExtractionCreate,
    service: ExtractionService = Depends(get_service),
    extractor: Extractor | None = Depends(get_extractor),
):
    return to_read(service.create(project_id, data.file_id, data.consent, extractor))


@router.get("/projects/{project_id}/extractions", response_model=list[ExtractionRead])
def list_extractions(project_id: int, service: ExtractionService = Depends(get_service)):
    return [to_read(extraction) for extraction in service.list(project_id)]


@router.post("/extractions/{extraction_id}/apply", response_model=ExtractionRead)
def apply_extraction(
    extraction_id: int,
    data: ExtractionApply,
    service: ExtractionService = Depends(get_service),
):
    return to_read(service.apply(extraction_id, data))


@router.post("/extractions/{extraction_id}/undo", response_model=ExtractionRead)
def undo_extraction(extraction_id: int, service: ExtractionService = Depends(get_service)):
    return to_read(service.undo(extraction_id))
