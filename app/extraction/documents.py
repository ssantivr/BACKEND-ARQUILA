"""Limits checked before a document reaches a provider. What cannot be checked is refused."""

import io
import logging
import struct
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Timeout

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.errors import InvalidDataError

MAX_PAGES = 10
MAX_PIXELS = 40_000_000
PARSE_SECONDS = 5.0

# pypdf reports repaired files through logging, with fragments of the document.
logging.getLogger("pypdf").setLevel(logging.CRITICAL)
_parser = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf-pages")


MAX_TREE_NODES = 200


def _pages_of(data: bytes) -> int | None:
    """Walks the page tree and stops as soon as it is over the limit: never the whole tree."""
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)

        if reader.is_encrypted:
            return None

        root = reader.trailer["/Root"].get_object()["/Pages"].get_object()
        declared = int(root.get("/Count", 0))

        if declared > MAX_PAGES:
            return declared

        pending, seen, pages = [root], set(), 0

        while pending:
            node = pending.pop().get_object()
            kids = node.get("/Kids")

            if id(node) in seen:
                return None

            seen.add(id(node))

            if len(seen) > MAX_TREE_NODES:
                return MAX_PAGES + 1

            if kids is None:
                pages += 1

                if pages > MAX_PAGES:
                    return pages
            else:
                pending.extend(kids.get_object())

        return pages
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return None


def count_pages(data: bytes) -> int | None:
    """The pages of a PDF, or None when they cannot be counted in time."""
    future = _parser.submit(_pages_of, data)

    try:
        pages = future.result(timeout=PARSE_SECONDS)
    except Timeout:
        future.cancel()
        return None
    except Exception:
        return None

    return pages if pages else None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None

    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    offset = 2

    while offset < len(data):
        if data[offset] != 0xFF:
            return None

        while offset < len(data) and data[offset] == 0xFF:
            offset += 1

        if offset >= len(data):
            return None

        marker = data[offset]
        offset += 1

        if marker in {0x01, 0xD8, 0xD9, *range(0xD0, 0xD8)}:
            continue

        if offset + 2 > len(data):
            return None

        segment_length = int.from_bytes(data[offset : offset + 2], "big")

        if segment_length < 2 or offset + segment_length > len(data):
            return None

        if marker in start_of_frame:
            if segment_length < 7:
                return None

            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height

        if marker == 0xDA:
            return None

        offset += segment_length

    return None


def check_document(data: bytes, mime_type: str) -> None:
    if mime_type == "application/pdf":
        pages = count_pages(data)

        if pages is None:
            raise InvalidDataError("The pages of the document cannot be counted")

        if pages > MAX_PAGES:
            raise InvalidDataError(f"The document has more than {MAX_PAGES} pages")

    elif mime_type == "image/png":
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise InvalidDataError("The size of the image cannot be read")

        width, height = struct.unpack(">II", data[16:24])

        if width == 0 or height == 0 or width * height > MAX_PIXELS:
            raise InvalidDataError("The image is too large to be read")
    elif mime_type == "image/jpeg":
        dimensions = _jpeg_size(data)

        if dimensions is None:
            raise InvalidDataError("The size of the image cannot be read")

        width, height = dimensions

        if width == 0 or height == 0 or width * height > MAX_PIXELS:
            raise InvalidDataError("The image is too large to be read")
