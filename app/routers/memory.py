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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.deps import current_user_optional
from app.data.uci_general.major_requirements import (
    get_major, compute_progress,
)


router = APIRouter()

MEMORY_ROOT = Path("data/memory")


# ── Helpers ──────────────────────────────────────────────

def _user_dir(user_id: str, *, create: bool = False) -> Path:
    """
    Resolve a user's memory dir. Path traversal is rejected. If
    create=True, the dir is mkdir'd on demand — used by write
    endpoints so a freshly-signed-up account doesn't have to seed
    its directory before its first write. Read endpoints pass
    create=False and handle the missing-dir case themselves.
    """
    if not user_id or "/" in user_id or "\\" in user_id or ".." in user_id:
        raise HTTPException(status_code=400, detail="Invalid user_id")
    path = MEMORY_ROOT / user_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
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
#
# Endpoint paths still take {user_id} for backward compatibility with
# the existing frontend (USER_ID = 'demo_001'), but the authoritative
# user id comes from the session cookie via current_user_optional.
# Unauthenticated callers fall back to demo_001 — the legacy demo
# flow keeps working with no frontend change required.

@router.get("/api/memory/{user_id}")
def get_memory(user_id: str, user: dict = Depends(current_user_optional)):
    real_user_id = user["id"]
    user_dir = _user_dir(real_user_id)

    # Brand-new authenticated account: dir hasn't been written yet.
    # Return empty payload rather than 404 — the frontend treats this
    # as "first-time user" and triggers onboarding (Phase C).
    if not user_dir.exists() or not user_dir.is_dir():
        return {
            "user_id": real_user_id,
            "profile": {},
            "facts":   {},
            "preferences": [],
            "major_progress": None,
        }

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
        "user_id": real_user_id,
        "profile": profile,
        "facts":   facts,
        "preferences": prefs,
        "major_progress": progress,
    }


# ── POST profile (onboarding write + later profile-editor) ──
#
# Generic merge-update endpoint. Used by:
#   - Phase C onboarding wizard (writes major/year/school + courses)
#   - Phase D profile editor (toggles completed_courses)
# Path user_id is ignored — real user comes from session cookie.
# For brand-new users we mkdir on demand so the wizard's very first
# save doesn't 404.

class ProfileUpdate(BaseModel):
    major:             Optional[str]       = None
    year:              Optional[str]       = None
    college:           Optional[str]       = None
    school_slug:       Optional[str]       = None
    program_id:        Optional[str]       = None  # Anteater id, e.g. "BS-201"
    completed_courses: Optional[list[str]] = None
    selected_courses:  Optional[list[str]] = None


@router.post("/api/memory/{user_id}/profile")
def update_profile(
    user_id: str, body: ProfileUpdate,
    user: dict = Depends(current_user_optional),
):
    real_user_id = user["id"]
    user_dir = _user_dir(real_user_id, create=True)
    path = user_dir / "profile.json"

    profile = _read_json(path, default={}) or {}
    if not isinstance(profile, dict):
        profile = {}

    updates = body.model_dump(exclude_none=True)
    # Treat "" / [] as "skip" so partial submissions don't blank fields
    # the user didn't touch on this round. Lists are deduplicated +
    # stable-sorted so re-submits don't churn the file.
    cleaned: dict = {}
    for k, v in updates.items():
        if isinstance(v, str):
            v = v.strip()
            if v:
                cleaned[k] = v
        elif isinstance(v, list):
            # Drop empties + dedupe (preserve first-seen order)
            seen, deduped = set(), []
            for item in v:
                if not isinstance(item, str): continue
                item = item.strip().upper()
                if item and item not in seen:
                    seen.add(item)
                    deduped.append(item)
            if deduped:
                cleaned[k] = deduped

    if not cleaned:
        return {"ok": True, "profile": profile, "updated": []}

    profile.update(cleaned)
    _write_json(path, profile)
    return {"ok": True, "profile": profile, "updated": list(cleaned.keys())}


# ── DELETE one preference ────────────────────────────────

@router.delete("/api/memory/{user_id}/preferences/{pref_id}")
def forget_preference(
    user_id: str, pref_id: str,
    user: dict = Depends(current_user_optional),
):
    real_user_id = user["id"]
    user_dir = _user_dir(real_user_id)
    pref_path = user_dir / "preferences.json"

    if not pref_path.exists():
        raise HTTPException(status_code=404, detail="No preferences stored")

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
def forget_all_preferences(
    user_id: str,
    user: dict = Depends(current_user_optional),
):
    real_user_id = user["id"]
    user_dir = _user_dir(real_user_id, create=True)
    pref_path = user_dir / "preferences.json"

    prefs = _read_json(pref_path, default=[])
    removed = len(prefs) if isinstance(prefs, list) else 0

    _write_json(pref_path, [])
    return {"ok": True, "removed": removed}