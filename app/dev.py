import os

import uvicorn

from app.env import ENV_FILE, load_env_file, require_database_url


def main() -> None:
    loaded = load_env_file(ENV_FILE)

    if loaded:
        print("Loaded from .env: " + ", ".join(loaded))

    require_database_url()

    from app.database import get_engine
    from app.migrate import apply_migrations

    applied = apply_migrations(get_engine())

    if applied:
        print("Applied migrations: " + ", ".join(applied))

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8010")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
