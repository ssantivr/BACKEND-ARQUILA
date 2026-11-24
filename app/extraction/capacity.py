"""How many readings run at once. The calls are synchronous and each one holds a worker thread."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from app.errors import TooManyAttemptsError

MAX_AT_ONCE = 4

_lock = Lock()
_reading: set[int] = set()


@contextmanager
def reading_slot(user_id: int) -> Iterator[None]:
    with _lock:
        if user_id in _reading:
            raise TooManyAttemptsError("A document is already being read")

        if len(_reading) >= MAX_AT_ONCE:
            raise TooManyAttemptsError("The document reader is busy")

        _reading.add(user_id)

    try:
        yield
    finally:
        with _lock:
            _reading.discard(user_id)
