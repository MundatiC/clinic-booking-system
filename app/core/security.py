"""Password hashing, opaque tokens, and the password policy."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import BusinessRuleError

# argon2id with the library's (OWASP-aligned) defaults. Tests swap in a cheap hasher.
hasher = PasswordHasher()
# Verified against when the email is unknown, so both paths cost the same.
_DUMMY_HASH = hasher.hash("timing-equaliser-not-a-real-password")

PASSWORD_MIN, PASSWORD_MAX = 10, 128

# NIST 800-63B: block known-breached/common choices instead of composition rules.
# shortcut: a short embedded list, upgrade to a k-anonymity breach check (HIBP) if needed.
_COMMON = frozenset(
    [
        "password",
        "password1",
        "password12",
        "password123",
        "password1234",
        "passw0rd",
        "passw0rd1",
        "1234567890",
        "0123456789",
        "12345678910",
        "1111111111",
        "0000000000",
        "qwertyuiop",
        "qwerty1234",
        "qwerty12345",
        "asdfghjkl1",
        "1q2w3e4r5t",
        "1qaz2wsx3edc",
        "zaq12wsxcde",
        "iloveyou12",
        "iloveyou123",
        "letmein123",
        "welcome123",
        "welcome1234",
        "admin12345",
        "administrator",
        "changeme123",
        "football123",
        "baseball123",
        "sunshine123",
        "princess123",
        "dragon1234",
        "monkey1234",
        "abc1234567",
        "abcdefghij",
        "trustno1234",
        "superman123",
        "starwars123",
        "whatever123",
        "computer123",
        "internet123",
        "nairobi123",
        "nairobi1234",
        "kenya12345",
        "kenya123456",
        "safaricom123",
        "mpesa12345",
        "clinic1234",
        "doctor1234",
        "hospital123",
        "qwertyuiop1",
        "password!!",
        "p@ssw0rd123",
        "p@ssword123",
    ]
)


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return hasher.check_needs_rehash(password_hash)


def check_password_policy(password: str, email: str) -> None:
    lowered = password.lower()
    local_part = email.split("@", 1)[0].lower()
    if len(password) < PASSWORD_MIN or len(password) > PASSWORD_MAX:
        problem = f"must be {PASSWORD_MIN}-{PASSWORD_MAX} characters long"
    elif lowered in _COMMON or len(set(password)) < 4:
        problem = "is too common or too easy to guess"
    elif len(local_part) >= 3 and local_part in lowered:
        problem = "must not contain your email address"
    else:
        return
    raise BusinessRuleError(
        "WEAK_PASSWORD",
        f"Password {problem}. A few unrelated words make a strong one.",
        {"min_length": PASSWORD_MIN, "max_length": PASSWORD_MAX},
    )


def new_token() -> tuple[str, bytes]:
    """A random URL-safe token and the SHA-256 digest that is stored instead of it."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> bytes:
    # Tokens are 256-bit random, so a fast unsalted hash is enough (no brute force).
    return hashlib.sha256(token.encode()).digest()
