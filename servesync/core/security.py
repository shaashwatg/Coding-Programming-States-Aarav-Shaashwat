"""
Password hashing with PBKDF2-HMAC-SHA256 (Python standard library only).

Passwords are never stored. We store a self-describing hash string in the
same layout Django uses, so the algorithm and cost can be raised later
without breaking existing accounts:

    pbkdf2_sha256$<iterations>$<salt (base64)>$<hash (base64)>

* A unique random 16-byte salt per password defeats pre-computed
  ("rainbow table") attacks.
* 600,000 iterations follows the OWASP Password Storage Cheat Sheet
  recommendation for PBKDF2-HMAC-SHA256.
* ``hmac.compare_digest`` compares in constant time so response timing
  cannot leak how many characters matched.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
SALT_BYTES = 16


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return an encoded hash for ``password`` using a fresh random salt."""
    if iterations < 1:
        raise ValueError("iterations must be positive")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(password, salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """
    Check ``password`` against a stored hash.

    Returns False (never raises) for a wrong password *or* a malformed hash,
    so a corrupted record cannot crash the sign-in screen.
    """
    try:
        algorithm, iterations_text, salt_b64, digest_b64 = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(iterations_text)
        if iterations < 1:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
    except (ValueError, AttributeError):  # wrong shape, bad int, bad base64
        return False
    actual = _derive(password, salt, iterations)
    return hmac.compare_digest(actual, expected)


def needs_rehash(encoded: str, *, iterations: int = DEFAULT_ITERATIONS) -> bool:
    """True when a stored hash uses an outdated algorithm or a lower cost."""
    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != ALGORITHM:
        return True
    try:
        return int(parts[1]) < iterations
    except ValueError:
        return True
