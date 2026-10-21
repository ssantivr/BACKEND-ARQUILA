import time
from threading import Lock

from sqlalchemy.orm import Session

from app.data_structures import Queue
from app.services import state_store

MAX_FAILED_ATTEMPTS = 5
WINDOW_SECONDS = 60.0
MAX_TRACKED_KEYS = 10000
MAX_RESET_REQUESTS = 3
RESET_WINDOW_SECONDS = 900.0
MAX_PASSWORD_CHANGE_FAILURES = 5
PASSWORD_CHANGE_WINDOW_SECONDS = 900.0
# Failed logins from one address, whatever the emails tried: it stops someone who tries many
# accounts, which the limit per email alone does not see.
MAX_FAILED_ATTEMPTS_PER_IP = 30
IP_WINDOW_SECONDS = 300.0


def now() -> float:
    return time.monotonic()


def wall_clock() -> float:
    return time.time()


def values_of(failures: Queue[float]) -> list[float]:
    values = []

    for _ in range(len(failures)):
        moment = failures.dequeue()
        values.append(moment)
        failures.enqueue(moment)

    return values


class LoginLimiter:
    def __init__(
        self,
        scope: str = "login",
        max_attempts: int = MAX_FAILED_ATTEMPTS,
        window_seconds: float = WINDOW_SECONDS,
        max_keys: int = MAX_TRACKED_KEYS,
    ) -> None:
        self._scope = scope
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._failures: dict[str, Queue[float]] = {}
        self._lock = Lock()

    def is_blocked(self, key: str, session: Session | None = None) -> bool:
        with self._lock:
            self._load(key, session)
            failures = self._drop_expired(key)
            return failures is not None and failures.is_full()

    def record_failure(self, key: str, session: Session | None = None) -> None:
        with self._lock:
            self._load(key, session)
            self._add_failure(key)
            self._save(key, session)

    def reset(self, key: str, session: Session | None = None) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._save(key, session)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()

    def _add_failure(self, key: str) -> None:
        failures = self._drop_expired(key)

        if failures is None:
            if len(self._failures) >= self._max_keys:
                self._purge_expired()

            if len(self._failures) >= self._max_keys:
                return

            failures = Queue(capacity=self._max_attempts)
            self._failures[key] = failures

        if not failures.is_full():
            failures.enqueue(now())

    def _load(self, key: str, session: Session | None) -> None:
        if not state_store.is_persistent(session):
            return

        stored = state_store.load(session, self._scope, key) or []
        offset = wall_clock() - now()
        failures: Queue[float] = Queue(capacity=self._max_attempts)

        for failed_at in sorted(stored)[-self._max_attempts :]:
            failures.enqueue(failed_at - offset)

        if failures.is_empty():
            self._failures.pop(key, None)
        else:
            self._failures[key] = failures

    def _save(self, key: str, session: Session | None) -> None:
        if not state_store.is_persistent(session):
            return

        failures = self._drop_expired(key)
        offset = wall_clock() - now()
        stored = None if failures is None else [moment + offset for moment in values_of(failures)]

        state_store.save(session, self._scope, key, stored)
        state_store.purge(session, self._scope, self._window_seconds)

    def _purge_expired(self) -> None:
        for key in list(self._failures):
            self._drop_expired(key)

    def _drop_expired(self, key: str) -> Queue[float] | None:
        failures = self._failures.get(key)

        if failures is None:
            return None

        limit = now() - self._window_seconds

        while not failures.is_empty() and failures.peek() <= limit:
            failures.dequeue()

        if failures.is_empty():
            del self._failures[key]
            return None

        return failures


login_limiter = LoginLimiter()
ip_login_limiter = LoginLimiter(
    scope="login_ip", max_attempts=MAX_FAILED_ATTEMPTS_PER_IP, window_seconds=IP_WINDOW_SECONDS
)
reset_request_limiter = LoginLimiter(
    scope="reset", max_attempts=MAX_RESET_REQUESTS, window_seconds=RESET_WINDOW_SECONDS
)
password_change_limiter = LoginLimiter(
    scope="password",
    max_attempts=MAX_PASSWORD_CHANGE_FAILURES,
    window_seconds=PASSWORD_CHANGE_WINDOW_SECONDS,
)
