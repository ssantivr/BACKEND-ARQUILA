import os
import time

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import (
    activity,
    auth,
    components,
    conversations,
    elevations,
    files,
    materials,
    plans,
    projects,
    recommendations,
    rooms,
    structure,
    summary,
    templates,
    terrains,
    undo,
    v1,
    versions,
)
from app.api.v1.validation import translate
from app.errors import (
    AuthenticationError,
    ConflictError,
    FileTooLargeError,
    InvalidDataError,
    InvalidTokenError,
    NotConfiguredError,
    NotFoundError,
    PermissionDeniedError,
    TooManyAttemptsError,
    UnsupportedFileError,
)
from app.logs import logger

DEFAULT_APP_URL = "http://localhost:5173"


def allowed_origins() -> list[str]:
    configured = os.environ.get("CORS_ORIGINS") or os.environ.get("APP_URL", DEFAULT_APP_URL)

    return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]


app = FastAPI(title="ARQUILA API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "frame-ancestors " + " ".join(["'self'", *allowed_origins()]),
}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)

    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)

    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    fields = {"method": request.method, "path": request.url.path}

    try:
        response = await call_next(request)
    except Exception:
        fields["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        logger.exception("request_failed", extra=fields)
        raise

    fields["status"] = response.status_code
    fields["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    logger.info("request", extra=fields)

    return response


app.include_router(auth.router)
app.include_router(files.router)
app.include_router(projects.router)
app.include_router(templates.router)
app.include_router(terrains.router)
app.include_router(materials.router)
app.include_router(plans.router)
app.include_router(elevations.router)
app.include_router(rooms.router)
app.include_router(components.router)
app.include_router(structure.router)
app.include_router(recommendations.router)
app.include_router(undo.router)
app.include_router(conversations.router)
app.include_router(summary.router)
app.include_router(activity.router)
app.include_router(versions.router)
app.include_router(v1.router)


@app.exception_handler(AuthenticationError)
def handle_unauthenticated(request: Request, error: AuthenticationError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(error)})


@app.exception_handler(TooManyAttemptsError)
def handle_too_many_attempts(request: Request, error: TooManyAttemptsError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": str(error)}
    )


@app.exception_handler(InvalidTokenError)
def handle_invalid_token(request: Request, error: InvalidTokenError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(error)})


@app.exception_handler(NotFoundError)
def handle_not_found(request: Request, error: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})


@app.exception_handler(ConflictError)
def handle_conflict(request: Request, error: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})


@app.exception_handler(IntegrityError)
def handle_integrity_error(request: Request, error: IntegrityError) -> JSONResponse:
    logger.warning("integrity_conflict", extra={"path": request.url.path})

    detail = (
        "El cambio entra en conflicto con datos que ya existen."
        if request.url.path.startswith(v1.API_PREFIX)
        else "The change conflicts with existing data"
    )

    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": detail})


@app.exception_handler(PermissionDeniedError)
def handle_permission_denied(request: Request, error: PermissionDeniedError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(error)})


@app.exception_handler(InvalidDataError)
def handle_invalid_data(request: Request, error: InvalidDataError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.exception_handler(NotConfiguredError)
def handle_not_configured(request: Request, error: NotConfiguredError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(error)}
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    if not request.url.path.startswith(v1.API_PREFIX):
        return await request_validation_exception_handler(request, error)

    return JSONResponse(
        status_code=422, content={"detail": [translate(issue) for issue in error.errors()]}
    )


@app.exception_handler(UnsupportedFileError)
def handle_unsupported_file(request: Request, error: UnsupportedFileError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        content={"detail": str(error)},
    )


@app.exception_handler(FileTooLargeError)
def handle_file_too_large(request: Request, error: FileTooLargeError) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(error)})


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
