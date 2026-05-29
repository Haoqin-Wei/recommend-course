"""
Password hashing + signed session cookies.

Password storage: bcrypt with the library's default cost (12 rounds
as of bcrypt 5.x). Migrate cost up by re-hashing on next login if we
ever need to.

Session cookies: itsdangerous URLSafeTimedSerializer. The cookie
contains JUST the user_id; we don't pack roles or anything else so
revocation is trivial — delete the user row and old cookies become
404-on-lookup. Cookie max-age is 30 days; clients with no activity
in that window get logged out.

Secret key: read from env AUTH_SESSION_SECRET, falling back to a
file at data/auth.secret that we generate once on first use. The
file is gitignored. Don't share it; rotating it logs every user out
which is the intended behavior on suspected compromise.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

SESSION_COOKIE_NAME = "zotadvisor_session"
SESSION_MAX_AGE_S = 30 * 24 * 3600  # 30 days
_SECRET_FILE = Path("data/auth.secret")


# ── Secret key resolution ────────────────────────────────

def _load_or_create_secret() -> str:
    env = os.environ.get("AUTH_SESSION_SECRET")
    if env:
        return env
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text().strip()
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    _SECRET_FILE.write_text(secret)
    _SECRET_FILE.chmod(0o600)
    return secret


_serializer: Optional[URLSafeTimedSerializer] = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(
            _load_or_create_secret(),
            salt="zotadvisor.session.v1",
        )
    return _serializer


# ── Passwords ────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash. plain must be UTF-8 < 72 bytes (bcrypt limit)."""
    if not plain:
        raise ValueError("password is empty")
    pwd_bytes = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt verify. Returns False on any malformed input."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Verification codes (also bcrypt — same primitive) ────

def hash_code(code: str) -> str:
    """Hash a 6-digit verification code so it isn't stored in plaintext."""
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_code(submitted: str, hashed: str) -> bool:
    if not submitted or not hashed:
        return False
    try:
        return bcrypt.checkpw(submitted.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Session cookies ──────────────────────────────────────

def sign_session(user_id: str) -> str:
    """Encode user_id into a signed token suitable for a cookie value."""
    return _get_serializer().dumps({"u": user_id})


def verify_session(token: str) -> Optional[str]:
    """
    Decode a session cookie. Returns the user_id or None if the
    token is missing, malformed, tampered with, or expired.
    """
    if not token:
        return None
    try:
        payload = _get_serializer().loads(token, max_age=SESSION_MAX_AGE_S)
    except (BadSignature, SignatureExpired):
        return None
    if isinstance(payload, dict):
        return payload.get("u")
    return None
