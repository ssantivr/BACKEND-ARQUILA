import os
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.errors import FileTooLargeError, UnsupportedFileError

MAX_FILE_BYTES = 20 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
DATABASE_PATH = "database"
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")


def upload_dir() -> Path:
    return Path(os.environ.get("UPLOAD_DIR", "uploads")).resolve()


def keeps_files_in_database() -> bool:
    return os.environ.get("FILE_STORAGE", "disk").lower() == "database"


def too_large() -> FileTooLargeError:
    return FileTooLargeError(f"File exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB limit")


def detect_type(head: bytes) -> tuple[str, str] | None:
    if head.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"

    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"

    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"

    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"

    return None


def require_type(head: bytes) -> tuple[str, str]:
    detected = detect_type(head)

    if detected is None:
        raise UnsupportedFileError("Only PDF, PNG, JPEG and WebP files are supported")

    return detected


def read(stream: BinaryIO) -> tuple[bytes, str]:
    head = stream.read(16)
    mime_type, _ = require_type(head)
    data = head + stream.read(MAX_FILE_BYTES + 1 - len(head))

    if len(data) > MAX_FILE_BYTES:
        raise too_large()

    return data, mime_type


def store(stream: BinaryIO) -> tuple[str, str, int]:
    head = stream.read(16)
    mime_type, extension = require_type(head)
    stored_name = f"{uuid4().hex}{extension}"
    directory = upload_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / stored_name
    size = 0

    try:
        with target.open("wb") as output:
            chunk = head

            while chunk:
                size += len(chunk)

                if size > MAX_FILE_BYTES:
                    raise too_large()

                output.write(chunk)
                chunk = stream.read(CHUNK_BYTES)
    except BaseException:
        target.unlink(missing_ok=True)
        raise

    return stored_name, mime_type, size


def path_for(stored_name: str) -> Path:
    return upload_dir() / Path(stored_name).name


def remove(stored_name: str) -> None:
    if stored_name != DATABASE_PATH:
        path_for(stored_name).unlink(missing_ok=True)
