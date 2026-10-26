"""Password hashing and checking for ``AUTH_PROVIDER=password``.

scrypt from the standard library: memory-hard, so GPU guessing is expensive,
and no native dependency to build on every platform. The stored form is
self-describing — ``scrypt$<n>$<r>$<p>$<salt>$<hash>`` — so the cost can be
raised later without invalidating existing hashes; :func:`needs_rehash` tells
the login path when to upgrade one.

A password is never logged, returned, or stored anywhere but ``password_hash``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

# 16 MiB of memory per hash (128 * n * r bytes); ~50 ms on a server core.
_N, _R, _P = 2**14, 8, 1
_KEY_LEN = 32
_MAXMEM = 64 * 1024 * 1024

MIN_LENGTH = 8
MAX_LENGTH = 128


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM, dklen=_KEY_LEN
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. A missing or malformed hash never matches."""
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = _derive(password, _unb64(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, _unb64(digest))


def needs_rehash(stored: str) -> bool:
    return not stored.startswith(f"scrypt${_N}${_R}${_P}$")


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def burn_time(password: str) -> None:
    """Spend the cost of one verification. Called when no account matched, so
    "unknown email" and "wrong password" take the same time to answer."""
    verify_password(password, _DUMMY_HASH)


def password_problem(password: str) -> str | None:
    """Why a new password is unacceptable, or None if it is fine."""
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Password must be at most {MAX_LENGTH} characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        return "Password must contain at least one letter and one number."
    return None
