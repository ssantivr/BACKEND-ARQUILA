import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

ARGON2_PREFIX = "$argon2"
LEGACY_SCHEME = "scrypt"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_BYTES = 32

# Argon2id above the RFC 9106 low-memory profile (3 passes). A password hashed with less is
# hashed again the next time its owner signs in.
ARGON2_TIME_COST = 4
ARGON2_MEMORY_KIB = 64 * 1024
ARGON2_PARALLELISM = 4

_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_KIB,
    parallelism=ARGON2_PARALLELISM,
)


def _derive_legacy(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
    )


def _verify_legacy(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, key_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(key_hex)
    except ValueError:
        return False

    if scheme != LEGACY_SCHEME:
        return False

    return hmac.compare_digest(_derive_legacy(password, salt), expected)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False

    if not stored.startswith(ARGON2_PREFIX):
        return _verify_legacy(password, stored)

    try:
        return _hasher.verify(stored, password)
    except (Argon2Error, InvalidHashError):
        return False


def needs_rehash(stored: str | None) -> bool:
    if not stored or not stored.startswith(ARGON2_PREFIX):
        return True

    try:
        return _hasher.check_needs_rehash(stored)
    except InvalidHashError:
        return True


DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
