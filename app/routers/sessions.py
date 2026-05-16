"""
Session CRUD API (Phase 3.2).

Five endpoints under /api/sessions/. Thin shells over app/data/sessions.py.
Exceptions from the data layer are translated to HTTP status codes here.

    GET    /api/sessions/{user_id}                    list (optional ?limit=N)
    POST   /api/sessions/{user_id}                    create
    GET    /api/sessions/{user_id}/{session_id}       meta + turns
    PATCH  /api/sessions/{user_id}/{session_id}       update title / term
    DELETE /api/sessions/{user_id}/{session_id}       delete

All endpoints take user_id in the path (multi-user is a future concern;
for now demo_001 is the single user, but the shape supports growth).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.data import sessions as S


router = APIRouter()


# ── Request body models ─────────────────────────────────

class CreateSessionBody(BaseModel):
    title:      Optional[str] = Field(default=None, max_length=200)
    term_scope: Optional[str] = Field(default=None, max_length=64)


class UpdateSessionBody(BaseModel):
    title:      Optional[str] = Field(default=None, max_length=200)
    term_scope: Optional[str] = Field(default=None, max_length=64)


# ── Exception translation helpers ───────────────────────

def _translate(exc: Exception) -> HTTPException:
    """Map data-layer exceptions to HTTP errors."""
    if isinstance(exc, S.InvalidId):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, S.SessionNotFound):
        return HTTPException(status_code=404, detail=f"Session not found: {exc}")
    return HTTPException(status_code=500, detail=f"Internal error: {exc}")


# ── Endpoints ───────────────────────────────────────────

@router.get("/api/sessions/{user_id}")
def list_sessions(
    user_id: str,
    limit: Optional[int] = Query(default=None, ge=1, le=200),
):
    """
    List all sessions for a user, sorted by last_active_at descending.
    Returns lightweight metadata only (no turns) — use the per-session
    endpoint to fetch a session's conversation history.
    """
    try:
        metas = S.list_sessions(user_id, limit=limit)
    except Exception as e:
        raise _translate(e)

    return {"user_id": user_id, "count": len(metas), "sessions": metas}


@router.post("/api/sessions/{user_id}")
def create_session(user_id: str, body: CreateSessionBody):
    """
    Create a new session. Both `title` and `term_scope` are optional;
    defaults are "New session" / null. Returns the new session's meta.
    """
    try:
        session_id = S.create_session(
            user_id,
            title=body.title,
            term_scope=body.term_scope,
        )
        meta = S.get_session_meta(user_id, session_id)
    except Exception as e:
        raise _translate(e)

    return meta


@router.get("/api/sessions/{user_id}/{session_id}")
def get_session(
    user_id: str,
    session_id: str,
    since_turn: int = Query(default=0, ge=0),
    include_turns: bool = Query(default=True),
):
    """
    Get a session's metadata, optionally with its conversation history.

    - since_turn: return only turns with turn_index > since_turn
      (useful once Phase 3.9 summarization lands — skip summarized prefix)
    - include_turns: set false for meta-only fetch (lighter payload)
    """
    try:
        meta = S.get_session_meta(user_id, session_id)
        if include_turns:
            turns = S.read_turns(user_id, session_id, since_turn=since_turn)
        else:
            turns = None
    except Exception as e:
        raise _translate(e)

    out = dict(meta)
    if include_turns:
        out["turns"] = turns
    return out


@router.patch("/api/sessions/{user_id}/{session_id}")
def update_session(user_id: str, session_id: str, body: UpdateSessionBody):
    """
    Partial update of session metadata. Currently supports title and
    term_scope; other fields are managed by the system (created_at,
    turn_count, decisions, summary).

    Pass only the fields you want to change. Returns the new meta.
    """
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        meta = S.update_session_meta(user_id, session_id, **fields)
    except Exception as e:
        raise _translate(e)

    return meta


@router.delete("/api/sessions/{user_id}/{session_id}")
def delete_session(user_id: str, session_id: str):
    """
    Delete a session and its turns. Idempotent: deleting a session that
    doesn't exist returns ok=False with HTTP 200 (rather than 404), so
    a refresh loop on the frontend doesn't need special handling.
    """
    try:
        ok = S.delete_session(user_id, session_id)
    except Exception as e:
        raise _translate(e)

    return {"ok": ok, "session_id": session_id}