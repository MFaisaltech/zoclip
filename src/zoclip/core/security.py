import hashlib
import secrets
from threading import BoundedSemaphore

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
COOKIE_NAME = "zoclip_session"
OAUTH_COOKIE = "zoclip_oauth"
HASH_SLOTS = BoundedSemaphore(2)


def hash_password(candidate: str) -> str:
    with HASH_SLOTS:
        return PASSWORD_HASHER.hash(candidate)


def token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(stored: str | None, candidate: str) -> bool:
    try:
        with HASH_SLOTS:
            return PASSWORD_HASHER.verify(stored or DUMMY_HASH, candidate) and stored is not None
    except (VerificationError, InvalidHashError):
        return False
