import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.env import setting
from app.models import RuntimeState


def keeps_state_in_database() -> bool:
    return setting("STATE_STORAGE").lower() == "database"


def is_persistent(session: Session | None) -> bool:
    return session is not None and keeps_state_in_database()


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def load(session: Session, scope: str, key: str) -> Any | None:
    row = session.get(RuntimeState, (scope, key), with_for_update=True)

    return None if row is None else json.loads(row.payload)


def save(session: Session, scope: str, key: str, payload: Any | None) -> None:
    row = session.get(RuntimeState, (scope, key))

    if payload is None:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(
            RuntimeState(scope=scope, key=key, payload=json.dumps(payload), updated_at=utc_now())
        )
    else:
        row.payload = json.dumps(payload)
        row.updated_at = utc_now()

    session.commit()


def purge(session: Session, scope: str, max_age_seconds: float) -> None:
    limit = utc_now() - timedelta(seconds=max_age_seconds)

    session.execute(
        delete(RuntimeState).where(RuntimeState.scope == scope, RuntimeState.updated_at < limit)
    )
    session.commit()
