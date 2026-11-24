from argon2 import PasswordHasher, extract_parameters

from app import security
from app.models import User
from tests.helpers import PASSWORD, register


def test_new_passwords_use_argon2id_with_the_stronger_parameters():
    stored = security.hash_password(PASSWORD)
    used = extract_parameters(stored)

    assert stored.startswith("$argon2id$")
    assert (used.time_cost, used.memory_cost, used.parallelism) == (4, 65536, 4)
    assert PASSWORD not in stored


def test_a_weaker_hash_is_replaced_at_the_next_sign_in(client, engine):
    from sqlalchemy.orm import Session

    register(client)
    weaker = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4).hash(PASSWORD)

    with Session(engine) as session:
        user = session.query(User).one()
        user.password_hash = weaker
        session.commit()
        email = user.email

    assert (
        client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    )

    with Session(engine) as session:
        stored = session.query(User).one().password_hash

    assert stored != weaker
    assert extract_parameters(stored).time_cost == 4


def test_a_rehash_never_undoes_a_password_reset(client, engine, monkeypatch):
    from sqlalchemy.orm import Session

    register(client)
    weaker = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4).hash(PASSWORD)
    changed = security.hash_password("another-password-entirely")

    with Session(engine) as session:
        user = session.query(User).one()
        user.password_hash = weaker
        session.commit()
        email = user.email

    def reset_meanwhile(password):
        with Session(engine) as session:
            session.query(User).one().password_hash = changed
            session.commit()

        return weaker

    monkeypatch.setattr(security, "hash_password", reset_meanwhile)
    sent = {"email": email, "password": PASSWORD}

    assert client.post("/auth/login", json=sent).status_code == 401

    with Session(engine) as session:
        assert session.query(User).one().password_hash == changed
