"""Security utilities: password hashing and JWT token management.

MVP implementation using hashlib + random salt (avoids bcrypt dependency).
For production, consider migrating to bcrypt or argon2.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from backend.app.core.config import get_settings

# ---------------------------------------------------------------------------
# Password hashing (hashlib + salt — lightweight for MVP)
# ---------------------------------------------------------------------------

_HASH_ITERATIONS = 100_000
_HASH_ALGORITHM = "sha256"


def hash_password(plain: str) -> str:
    """Return ``salt$hash`` string for the given plaintext password."""
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac(_HASH_ALGORITHM, plain.encode(), salt.encode(), _HASH_ITERATIONS)
    return f"{salt}${dk.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    """Verify *plain* against a ``salt$hash`` string produced by :func:`hash_password`."""
    try:
        salt, expected_hex = hashed.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac(_HASH_ALGORITHM, plain.encode(), salt.encode(), _HASH_ITERATIONS)
    return dk.hex() == expected_hex


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT containing *data* with an expiry claim."""
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.  Raises ``jwt.PyJWTError`` on failure."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
