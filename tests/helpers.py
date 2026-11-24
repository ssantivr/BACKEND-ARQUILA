from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import Permission, Role, User

PASSWORD = "correct-horse-battery-7"


def register(client, name="Ana", email="ana@example.com", password=PASSWORD):
    response = client.post(
        "/auth/register", json={"name": name, "email": email, "password": password}
    )
    assert response.status_code == 201, response.text
    return response.json()


READ_PERMISSIONS = {"units:read", "rooms:read", "spatial:read", "walkthrough:read"}
WRITE_PERMISSIONS = {"units:write", "rooms:write", "spatial:write", "walkthrough:write"}

# Mirrors migration 012 of BASE-DE-DATOS-ARQUILA, which is what a real database holds.
ROLE_PERMISSIONS = {
    "admin": READ_PERMISSIONS | WRITE_PERMISSIONS | {"roles:manage"},
    "architect": READ_PERMISSIONS | WRITE_PERMISSIONS,
    "viewer": READ_PERMISSIONS,
}


def seed_access_catalog(engine: Engine) -> None:
    with Session(engine) as session:
        permissions = {
            code: Permission(code=code, description=code)
            for code in sorted(ROLE_PERMISSIONS["admin"])
        }

        session.add_all(
            Role(name=name, description=name, permissions=[permissions[code] for code in codes])
            for name, codes in ROLE_PERMISSIONS.items()
        )
        session.commit()


def set_roles(engine: Engine, email: str, *names: str) -> None:
    with Session(engine) as session:
        user = session.query(User).filter_by(email=email).one()
        user.roles = session.query(Role).filter(Role.name.in_(names)).all()
        session.commit()
