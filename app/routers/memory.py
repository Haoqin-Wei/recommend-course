"""
Memory inspection API.

Powers the Memory panel in the UI — lets users see what ZotAdvisor
remembers about them (facts, preferences, major progress) and forget
individual preferences or all of them.

Endpoints:
    GET  /api/memory/{user_id}                              snapshot
    DELETE /api/memory/{user_id}/preferences/{pref_id}      forget one
    POST /api/memory/{user_id}/preferences/forget_all       wipe prefs

Memory layout on disk (one folder per user):
    data/memory/{user_id}/
      profile.json     hard facts (major, year, completed_courses, ...)
      facts.json       Channel A extraction snapshots (often overlaps profile)
      preferences.json [{id, text, learned_at}, ...]  Channel B output

The DELETE/POST endpoints rewrite preferences.json. Concurrency isn't a
concern for this demo (single user per file), but writes are atomic via
read-modify-write on the whole array.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.data.uci_general.major_requirements import (
    get_major, compute_progress,
)


router = APIRouter()

MEMORY_ROOT = Path("data/memory")


# ── Helpers ──────────────────────────────────────────────

def _user_dir(user_id: str) -> Path:
    """Resolve and validate a user's memory dir. Raises 4xx on bad input."""
    # Defensive: prevent path traversal.
    if not user_id or "/" in user_id or "\\" in user_id or ".." in user_id:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    path = MEMORY_ROOT / user_id
    if not path.exists() or not path.is_dir():
        raise HTTPException(
            status_code=404, detail=f"No memory directory for user {user_id!r}",
        )
    return path


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# Names students might say → catalogue slug. Add entries as more majors
# get hand-encoded. Unrecognized names → no progress section in response.
_MAJOR_NAME_TO_SLUG: dict[str, str] = {
    "computer science":     "computerscience_bs",
    "computer science b.s.": "computerscience_bs",
    "cs":                   "computerscience_bs",
    # "data science":         "datascience_bs",       # future
    # "software engineering": "softwareengineering_bs",
    # "informatics":          "informatics_bs",
}


def _major_slug_from_profile(profile: dict) -> Optional[str]:
    raw = (profile or {}).get("major", "")
    if not isinstance(raw, str):
        return None
    return _MAJOR_NAME_TO_SLUG.get(raw.strip().lower())


# ── GET snapshot ─────────────────────────────────────────

@router.get("/api/memory/{user_id}")
def get_memory(user_id: str):
    user_dir = _user_dir(user_id)

    profile = _read_json(user_dir / "profile.json", default={}) or {}
    prefs   = _read_json(user_dir / "preferences.json", default=[]) or []
    facts   = _read_json(user_dir / "facts.json", default={}) or {}

    # Coerce shapes defensively (the JSON files are user-editable).
    if not isinstance(profile, dict):
        profile = {}
    if not isinstance(prefs, list):
        prefs = []
    if not isinstance(facts, dict):
        facts = {}

    # Compute major progress (only for hand-crafted majors).
    progress = None
    slug = _major_slug_from_profile(profile)
    if slug:
        major = get_major(slug)
        if isinstance(major, dict) and "specializations" in major:
            progress = compute_progress(
                slug,
                completed=profile.get("completed_courses") or [],
                in_progress=profile.get("selected_courses") or [],
            )
            progress["name"]   = major.get("name", "")
            progress["degree"] = major.get("degree", "")
            progress["slug"]   = slug

    return {
        "user_id": user_id,
        "profile": profile,
        "facts":   facts,
        "preferences": prefs,
        "major_progress": progress,
    }


# ── DELETE one preference ────────────────────────────────

@router.delete("/api/memory/{user_id}/preferences/{pref_id}")
def forget_preference(user_id: str, pref_id: str):
    user_dir = _user_dir(user_id)
    pref_path = user_dir / "preferences.json"

    prefs = _read_json(pref_path, default=[])
    if not isinstance(prefs, list):
        raise HTTPException(status_code=500, detail="preferences.json is malformed")

    before = len(prefs)
    kept = [
        p for p in prefs
        if not (isinstance(p, dict) and p.get("id") == pref_id)
    ]
    if len(kept) == before:
        raise HTTPException(
            status_code=404,
            detail=f"No preference with id {pref_id!r}",
        )

    _write_json(pref_path, kept)
    return {"ok": True, "removed": pref_id, "remaining": len(kept)}


# ── POST forget all preferences ──────────────────────────

@router.post("/api/memory/{user_id}/preferences/forget_all")
def forget_all_preferences(user_id: str):
    user_dir = _user_dir(user_id)
    pref_path = user_dir / "preferences.json"

    prefs = _read_json(pref_path, default=[])
    removed = len(prefs) if isinstance(prefs, list) else 0

    _write_json(pref_path, [])
    return {"ok": True, "removed": removed}