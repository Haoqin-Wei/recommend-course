"""
Major requirements registry.

Hand-crafted major requirement dicts (one Python module per major,
in this package) are registered here. Future expansion:
add data_science_bs.py, software_engineering_bs.py, informatics_bs.py,
register them in `_REGISTRY` below.

Raw (un-handcrafted) data for all 86 majors lives in
data/uci_general/major_requirements_raw/<slug>.json, output from
scripts/scrape_major_requirements.py. Use those when fine grain isn't
needed — the raw file lists every course referenced on the catalogue
page, which is enough for "is this course relevant to major X?"
quick checks.

Public API:
    get_major(slug)           → dict | None
    list_majors()             → list[dict]   (lightweight summaries)
    courses_for_major(slug)   → set[str]     (everything referenced)
    compute_progress(slug, completed, in_progress=None) → ProgressReport
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import cs_bs


# ── Registry of fully hand-crafted majors ──────────────────
_REGISTRY: dict[str, dict] = {
    "computerscience_bs": cs_bs.get(),
    # Future:
    # "datascience_bs":          data_science_bs.get(),
    # "softwareengineering_bs":  software_engineering_bs.get(),
    # "informatics_bs":          informatics_bs.get(),
}


# Raw scraped data — only course IDs + raw text, no structure
_RAW_DIR = Path("data/uci_general/major_requirements_raw")


def get_major(slug: str) -> Optional[dict]:
    """
    Return a fully hand-crafted major dict, or fall back to raw scraped data
    if no handcraft exists. Returns None if unknown.
    """
    if slug in _REGISTRY:
        return _REGISTRY[slug]
    raw_path = _RAW_DIR / f"{slug}.json"
    if raw_path.exists():
        try:
            return json.loads(raw_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def list_majors() -> list[dict]:
    """
    Return lightweight summaries of every known major, prefer-handcraft.
    Each entry: {slug, name, degree, school, has_handcraft: bool}
    """
    out: list[dict] = []
    seen: set[str] = set()

    for slug, major in _REGISTRY.items():
        out.append({
            "slug":     slug,
            "name":     major.get("name", ""),
            "degree":   major.get("degree", ""),
            "school":   major.get("school", ""),
            "has_handcraft": True,
        })
        seen.add(slug)

    if _RAW_DIR.exists():
        for raw_path in sorted(_RAW_DIR.glob("*.json")):
            slug = raw_path.stem
            if slug in seen:
                continue
            try:
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            label = raw.get("label", "")
            # label format: "Major Name, Degree" e.g. "Computer Science, B.S."
            name, _, degree = label.partition(",")
            out.append({
                "slug":     slug,
                "name":     name.strip(),
                "degree":   degree.strip(),
                "school":   raw.get("school", ""),
                "has_handcraft": False,
            })
            seen.add(slug)

    return out


def courses_for_major(slug: str) -> set[str]:
    """
    Return every course ID referenced anywhere in a major's requirements.
    For handcrafted majors: drawn from all required/scope/choice fields.
    For raw majors: drawn from the scraper's `course_refs` list.

    All IDs returned in *colloquial* form (CS122A, ICS33). Raw refs
    using catalogue form ('I&C SCI 33') are converted on the fly.
    """
    if slug in _REGISTRY:
        return cs_bs.all_required_anywhere() if slug == "computerscience_bs" else set()

    raw_path = _RAW_DIR / f"{slug}.json"
    if not raw_path.exists():
        return set()
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    return {_to_colloquial(r) for r in raw.get("course_refs", [])}


# ── Catalogue-form → colloquial conversion ─────────────────
# Catalogue uses spaced form: "I&C SCI 33", "MATH 2A", "COMPSCI 122A"
# We use compact form:        "ICS33",      "MATH2A", "CS122A"
#
# Mirror of departments.py prefix map. Kept local so this module can be
# imported standalone without pulling all of app.data.

_DEPT_PREFIX_MAP: dict[str, str] = {
    "COMPSCI":   "CS",
    "I&C SCI":   "ICS",
    "EECS":      "EECS",
    "CSE":       "CSE",
    "IN4MATX":   "IN4MATX",
    "MATH":      "MATH",
    "STATS":     "STATS",
    "SWE":       "SWE",
    "PHYSICS":   "PHYSICS",
    "CHEM":      "CHEM",
    "BIO SCI":   "BIOSCI",
    "EARTHSS":   "EARTHSS",
    "ECON":      "ECON",
    "PUBHLTH":   "PUBHLTH",
    "WRITING":   "WRITING",
    "PSYCH":     "PSYCH",
    "STATS":     "STATS",
}


def _to_colloquial(catalogue_ref: str) -> str:
    """
    'I&C SCI 33' → 'ICS33';  'MATH 2A' → 'MATH2A';  'COMPSCI 122A' → 'CS122A'.

    Unknown departments fall back to space-stripped form ('FOO BAR 1' → 'FOOBAR1').
    """
    parts = (catalogue_ref or "").strip().rsplit(" ", 1)
    if len(parts) != 2:
        return catalogue_ref.replace(" ", "")
    dept, num = parts
    prefix = _DEPT_PREFIX_MAP.get(dept, dept.replace(" ", ""))
    return f"{prefix}{num}"


# ── Coarse progress calculator (handcrafted majors only) ──

def compute_progress(
    slug: str,
    completed: list[str],
    in_progress: Optional[list[str]] = None,
) -> dict:
    """
    For a handcrafted major, compute simple completion counts.

    Returns a dict with overall and per-section counts. Coarse but enough
    for the demo UI's "X of Y core courses done" pill. For specialization
    progress and exact pick-K-from-N validity, future expansion needed.

    Example return for CS B.S.:
        {
          "lower_required":  {"done": 6, "total": 10},
          "lower_choice":    {"done": 1, "total": 2,
                              "satisfied_choices": ["Programming intro sequence"]},
          "upper_required":  {"done": 0, "total": 2},
          "upper_electives": {"done": 1, "total": 11},
          "specialization":  {"chosen": null, "progress": null},
          "overall_pct":     0.32,
        }
    """
    major = _REGISTRY.get(slug)
    if not major:
        return {"error": f"No handcrafted progress for slug {slug!r}"}

    completed_set = {c.upper() for c in completed}
    in_progress_set = {c.upper() for c in (in_progress or [])}
    counted = completed_set | in_progress_set     # both count for progress

    lower_req = major["lower_division"]["required_all"]
    lower_done = sum(1 for c in lower_req if c.upper() in counted)

    # Choice groups: one option's full set must be in `counted`.
    choice_done = 0
    satisfied: list[str] = []
    for grp in major["lower_division"]["choice_groups"]:
        for opt in grp["options"]:
            if all(c.upper() in counted for c in opt):
                choice_done += 1
                satisfied.append(grp["name"])
                break

    upper_req = major["upper_division"]["required_all"]
    upper_done = sum(1 for c in upper_req if c.upper() in counted)

    upper_elec_scope = major["upper_division"]["electives"]["scope_courses"]
    upper_elec_count = major["upper_division"]["electives"]["count"]
    upper_elec_done = min(
        upper_elec_count,
        sum(1 for c in upper_elec_scope if c.upper() in counted),
    )

    total_target = (
        len(lower_req)
        + len(major["lower_division"]["choice_groups"])
        + len(upper_req)
        + upper_elec_count
    )
    total_done = lower_done + choice_done + upper_done + upper_elec_done

    return {
        "lower_required":  {"done": lower_done, "total": len(lower_req)},
        "lower_choice":    {"done": choice_done,
                            "total": len(major["lower_division"]["choice_groups"]),
                            "satisfied_choices": satisfied},
        "upper_required":  {"done": upper_done, "total": len(upper_req)},
        "upper_electives": {"done": upper_elec_done, "total": upper_elec_count},
        # Specialization tracking left for future expansion.
        "specialization":  {"chosen": None, "progress": None},
        "overall_pct":     round(total_done / total_target, 2) if total_target else 0,
        "overall_done":    total_done,
        "overall_total":   total_target,
    }