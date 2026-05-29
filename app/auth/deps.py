"""
FastAPI dependencies for auth.

Two flavors, both read the session cookie:

  current_user_optional() → Optional[user_dict]
      Used by routes that already had a `demo_001` fallback. Real
      sessions take priority; unauthenticated callers still get a
      demo_001 stub so the existing demo stays functional during
      the Phase B rollout.

  current_user_required() → user_dict (or HTTPException 401)
      Used by routes that should reject anonymous access — newly
      added profile-edit endpoints, the onboarding flow, anything
      that mutates per-user state intentionally.

Both dependencies stay lightweight (one signed-cookie decode + one
SQLite SELECT). Per-request overhead is negligible for the demo.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Cookie, HTTPException, status

from app.auth import security, store

# Stand-in user record returned when a route allows anonymous access.
# Keeps existing data/memory/demo_001/ folder usable so the legacy
# demo flow still works while we migrate routes to real auth.
_DEMO_USER = {
    "id": "demo_001",
    "email": "demo@local",
    "verified_at": None,
    "created_at": None,
    "is_demo": True,
}


def current_user_optional(
    zotadvisor_session: Optional[str] = Cookie(default=None),
) -> dict:
    """Resolve the request's user, falling back to the demo account."""
    if zotadvisor_session:
        user_id = security.verify_session(zotadvisor_session)
        if user_id:
            row = store.find_user_by_id(user_id)
            if row:
                # Drop the password hash — never want this in route handlers.
                row.pop("password_hash", None)
                row["is_demo"] = False
                return row
    return _DEMO_USER


def current_user_required(
    zotadvisor_session: Optional[str] = Cookie(default=None),
) -> dict:
    """Resolve the request's user; 401 if no valid session."""
    if not zotadvisor_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")
    user_id = security.verify_session(zotadvisor_session)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired session")
    row = store.find_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="User no longer exists")
    row.pop("password_hash", None)
    row["is_demo"] = False
    return row
