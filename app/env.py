import os
from pathlib import Path

from app import tokens

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"

# Used when a variable is missing or empty. Production gets the safe values; development keeps
# working over plain HTTP, in one process and without the runtime_state and file_contents tables.
PRODUCTION_DEFAULTS = {
    "COOKIE_SECURE": "1",
    "STATE_STORAGE": "database",
    "FILE_STORAGE": "database",
}
DEVELOPMENT_DEFAULTS = {"COOKIE_SECURE": "0", "STATE_STORAGE": "memory", "FILE_STORAGE": "disk"}


def load_env_file(path: Path) -> list[str]:
    if not path.is_file():
        return []

    loaded = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)

    return loaded


def is_production() -> bool:
    """True with ENVIRONMENT=production, and always on Vercel, which sets VERCEL itself."""
    return os.environ.get("ENVIRONMENT", "").lower() == "production" or bool(
        os.environ.get("VERCEL")
    )


def setting(name: str) -> str:
    """The variable as set, or its default for this environment when it is missing or empty."""
    value = os.environ.get(name, "").strip()

    if value:
        return value

    return (PRODUCTION_DEFAULTS if is_production() else DEVELOPMENT_DEFAULTS)[name]


def insecure_settings() -> list[str]:
    """Names of the variables that leave a production server weaker. Never their values."""
    if not is_production():
        return []

    names = []

    if setting("COOKIE_SECURE") != "1":
        names.append("COOKIE_SECURE")

    if setting("STATE_STORAGE").lower() != "database":
        names.append("STATE_STORAGE")

    # A server of its own may keep its disk; Vercel never does.
    if os.environ.get("VERCEL") and setting("FILE_STORAGE").lower() != "database":
        names.append("FILE_STORAGE")

    # Optional: without it only /api/v1/auth/token stops working, so it never stops the server.
    if tokens.signing_secret() is None:
        names.append("JWT_SECRET")

    return names


def check_production_settings() -> None:
    # Imported here: app.dev imports this module before it loads .env, and importing app.logs
    # sets the log level, which would then miss a LOG_LEVEL written in .env.
    from app.logs import logger

    for name in insecure_settings():
        logger.warning("insecure_setting", extra={"variable": name})


def require_database_url() -> None:
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
