import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"


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


def require_database_url() -> None:
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
