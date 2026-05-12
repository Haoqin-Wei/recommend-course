"""
Database Access Layer — Real UCI data backed by data/uci/*.csv.

Reads from:
    data/uci/courses.csv               (from scripts/fetch_uci_data.py)
    data/uci/sections.csv              (from scripts/import_term_data.py)
    data/uci/section_instructors.csv   (from scripts/import_term_data.py)

Still mock-backed (until Phase 2.3 / 2.4):
    PROFESSOR_RATINGS    — RateMyProfessor data, not in Anteater API
    GRADE_DISTRIBUTIONS  — grades.csv not yet fetched
    DEMO_STUDENT         — demo profile only; student DB out of scope

The public interface is unchanged from the mock version. query.py and
chat.py do NOT need to be modified.

Conventions:
  - Public course_id is in COLLOQUIAL form ('CS122A', 'ICS33') so it
    matches the format LLM output uses and chat.py's regex expects.
  - Internal CSV join keys use canonical form ('COMPSCI_122A') —
    encapsulated, callers never see these.
  - Term parameters accept the display form ('Spring 2025'). Internally
    we convert to CSV form ('2025_Spring') or Anteater form
    ('2025 Spring') as needed.
"""

from __future__ import annotations

import csv
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.catalog.departments import (
    colloquial_course_id, resolve_department,
)
from app.data.mock_data import (
    PROFESSOR_RATINGS,
    GRADE_DISTRIBUTIONS,
    DEMO_STUDENT,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/uci")


# ── Term format helpers ──────────────────────────────────

def _term_display_to_id(t: str) -> str:
    """'Spring 2025' → '2025_Spring' (sections.csv form)."""
    parts = (t or "").strip().split()
    return f"{parts[1]}_{parts[0]}" if len(parts) == 2 else (t or "")


def _term_id_to_display(t: str) -> str:
    """'2025_Spring' → 'Spring 2025'."""
    parts = (t or "").split("_")
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 else (t or "")


def _term_display_to_anteater(t: str) -> str:
    """'Spring 2025' → '2025 Spring' (Anteater terms_offered format)."""
    parts = (t or "").strip().split()
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 else (t or "")


# ── CSV loaders (cached on first call) ───────────────────

@lru_cache(maxsize=1)
def _load_courses() -> dict[str, dict]:
    """All courses keyed by COLLOQUIAL course_id ('CS122A')."""
    path = DATA_DIR / "courses.csv"
    if not path.exists():
        logger.warning("db.py: %s missing — get_course_info will return None for all courses", path)
        return {}
    out = {}
    with path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = colloquial_course_id(r["department"], r["course_number"])
            if cid:
                out[cid] = r
    logger.info("db.py: loaded %d courses from %s", len(out), path)
    return out


@lru_cache(maxsize=1)
def _load_sections_by_course() -> dict[str, list[dict]]:
    """Sections grouped by COLLOQUIAL course_id."""
    path = DATA_DIR / "sections.csv"
    if not path.exists():
        logger.warning("db.py: %s missing — get_sections will return [] for all courses", path)
        return {}
    out: dict[str, list[dict]] = {}
    with path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = colloquial_course_id(r.get("department", ""), r.get("courseNumber", ""))
            if cid:
                out.setdefault(cid, []).append(r)
    logger.info("db.py: loaded sections for %d unique courses", len(out))
    return out


@lru_cache(maxsize=1)
def _load_section_instructors() -> dict[str, list[str]]:
    """Instructors grouped by section_id."""
    path = DATA_DIR / "section_instructors.csv"
    if not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = (r.get("section_id") or "").strip()
            name = (r.get("instructor_name_raw") or "").strip()
            if sid and name:
                out.setdefault(sid, []).append(name)
    return out


# ── Shape conversion: CSV row → dict that query.py / chat.py expect ──

def _to_course_dict(r: dict) -> dict:
    """Build the dict shape that downstream code (query.py, _build_card) expects."""
    ge_categories = [g for g in (r.get("ge_list") or "").split("|") if g]

    # Flatten prereqs to colloquial course IDs
    prereqs: list[str] = []
    try:
        for p in json.loads(r.get("prerequisites_flat_json") or "[]"):
            cid = colloquial_course_id(p.get("department", ""), p.get("course_number", ""))
            if cid:
                prereqs.append(cid)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    def _as_int(v: str, default: int = 0) -> int:
        try:
            return int(float(v)) if v else default
        except (ValueError, TypeError):
            return default

    return {
        # Required fields (used by query.py / chat.py / frontend)
        "course_id":         colloquial_course_id(r["department"], r["course_number"]),
        "title":             r.get("title", ""),
        "units":             _as_int(r.get("min_units", "")),
        "department":        r.get("department", ""),
        "description":       r.get("description", ""),
        "ge_category":       ge_categories[0] if ge_categories else None,
        "major_requirement": [],            # ⚠️ no source yet (Phase 2.5)
        # Extras (useful for future, harmless to expose now)
        "department_name":   r.get("department_name", ""),
        "ge_categories":     ge_categories,
        "prerequisites":     prereqs,
        "course_level":      r.get("course_level", ""),
        "course_numeric":    _as_int(r.get("course_numeric", "")),
        "same_as":           r.get("same_as", ""),
        "restriction":       r.get("restriction", ""),
        "prerequisite_text": r.get("prerequisite_text", ""),
    }


def _to_section_dict(r: dict, instructors: list[str]) -> dict:
    """Build the dict shape that query.py / chat.py / frontend expect for a section."""
    return {
        "section":        r.get("sectionCode", ""),
        "course_id":      colloquial_course_id(r.get("department", ""), r.get("courseNumber", "")),
        "instructor":     instructors[0] if instructors else "TBA",
        "instructors":    instructors,                          # bonus: full list
        "term":           _term_id_to_display(r.get("term_id", "")),
        "days":           r.get("days", ""),                    # not yet in data (Phase 2.2)
        "time":           r.get("time", ""),                    # ditto
        "location":       r.get("location", ""),                # ditto
    }


# ══════════════════════════════════════════════════════════
#  PUBLIC API — signatures unchanged from the mock version
# ══════════════════════════════════════════════════════════

# ── Student Profile ──────────────────────────────────────

def get_student_profile(student_id: str) -> Optional[dict]:
    """
    Demo data only. Real student DB out of scope for this project.
    """
    if student_id == DEMO_STUDENT["student_id"]:
        return DEMO_STUDENT
    return None


# ── Course Catalog ───────────────────────────────────────

def get_course_info(course_id: str) -> Optional[dict]:
    """Look up a single course by colloquial ID ('CS122A')."""
    courses = _load_courses()
    r = courses.get((course_id or "").upper().strip())
    return _to_course_dict(r) if r else None


def search_courses(
    term: Optional[str] = None,
    department: Optional[str] = None,
    major_requirement: Optional[str] = None,
    ge_category: Optional[str] = None,
    exclude_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Search course catalog with optional filters.

    term:                 'Spring 2025' display form. Filters to courses
                          that have this term in their `terms_offered_json`.
    department:           canonical 'COMPSCI' or alias 'cs' / 'computer science'.
    major_requirement:    'Computer Science' etc. Anteater doesn't supply
                          true major-requirement data yet, so we approximate
                          by mapping major → dept (e.g. 'Computer Science'
                          → COMPSCI) and filtering by that dept.
    ge_category:          'GE-2', 'GE-1A', etc.
    exclude_ids:          list of colloquial course IDs to omit.
    """
    courses = _load_courses()
    upper_exclude = {x.upper() for x in (exclude_ids or [])}

    # Resolve department aliases for filter
    target_dept = None
    if department:
        target_dept = resolve_department(department) or department.upper()

    # If major_requirement is set, map to a dept and use as filter
    # (best approximation until we have real major-requirement data).
    if major_requirement and not target_dept:
        mapped = resolve_department(major_requirement)
        if mapped:
            target_dept = mapped
            logger.info(
                "search_courses: mapped major=%r → department=%r",
                major_requirement, mapped,
            )
        else:
            logger.info(
                "search_courses: major_requirement=%r not mappable; filter ignored",
                major_requirement,
            )

    target_term_anteater = _term_display_to_anteater(term) if term else None

    results: list[dict] = []
    for cid, r in courses.items():
        if cid in upper_exclude:
            continue
        if target_dept and r.get("department", "").upper() != target_dept.upper():
            continue
        if ge_category:
            ges = (r.get("ge_list") or "").split("|")
            if ge_category not in ges:
                continue
        if target_term_anteater:
            try:
                terms = json.loads(r.get("terms_offered_json") or "[]")
            except json.JSONDecodeError:
                continue
            if target_term_anteater not in terms:
                continue
        results.append(_to_course_dict(r))

    return results


# ── Sections & Schedule ──────────────────────────────────

def get_sections(course_id: str, term: Optional[str] = None) -> list[dict]:
    """Sections for a course, optionally filtered by term ('Spring 2025')."""
    sections = _load_sections_by_course()
    instructors_by_section = _load_section_instructors()

    rows = sections.get((course_id or "").upper().strip(), [])
    target_term_id = _term_display_to_id(term) if term else None

    out: list[dict] = []
    for r in rows:
        if target_term_id and r.get("term_id") != target_term_id:
            continue
        instrs = instructors_by_section.get((r.get("section_id") or "").strip(), [])
        out.append(_to_section_dict(r, instrs))
    return out


def get_schedule_for_student(student_id: str, term: str) -> list[dict]:
    """The student's currently-enrolled sections this term."""
    profile = get_student_profile(student_id)
    if not profile:
        return []
    enrolled_ids = {c.upper() for c in profile.get("selected_courses", [])}
    if not enrolled_ids:
        return []

    sections = _load_sections_by_course()
    instructors_by_section = _load_section_instructors()
    target_term_id = _term_display_to_id(term) if term else None

    out: list[dict] = []
    for cid, rows in sections.items():
        if cid not in enrolled_ids:
            continue
        for r in rows:
            if target_term_id and r.get("term_id") != target_term_id:
                continue
            instrs = instructors_by_section.get((r.get("section_id") or "").strip(), [])
            out.append(_to_section_dict(r, instrs))
    return out


# ── Prerequisites ────────────────────────────────────────

def get_prerequisites(course_id: str) -> list[str]:
    """Return colloquial-form prereq IDs (flat list)."""
    course = get_course_info(course_id)
    return course.get("prerequisites", []) if course else []


def check_prerequisites_met(course_id: str, completed_courses: list[str]) -> dict:
    """
    Check if all listed prereqs have been completed.

    PHASE 2 SIMPLIFICATION: treats the prereq list as a flat AND-list.
    Real UCI prereqs have AND/OR logic in `prerequisite_tree_json`
    (e.g. CS122A needs "ICS33 OR EECS114") — Phase 3 will switch to
    the tree. For now, this errs on the strict side: students with
    partial-but-sufficient prereqs may see their target in `flagged`
    instead of `primary`.

    Returns {"met": bool, "missing": [str]}
    """
    prereqs = get_prerequisites(course_id)
    completed_upper = {c.upper() for c in completed_courses}
    missing = [p for p in prereqs if p.upper() not in completed_upper]
    return {"met": len(missing) == 0, "missing": missing}


# ── Professor Ratings (still mock) ───────────────────────

def get_professor_rating(instructor_name: str) -> Optional[dict]:
    """
    Still backed by mock PROFESSOR_RATINGS.

    PHASE 2.4 — will need to either scrape RateMyProfessor and key by
    'CAREY, M.' format (matching sections data), or drop ratings in
    favor of grade-distribution-based difficulty signals.
    """
    return PROFESSOR_RATINGS.get(instructor_name)


# ── Grade Distribution (still mock) ──────────────────────

def get_grade_distribution(course_id: str) -> Optional[dict]:
    """
    Still backed by mock GRADE_DISTRIBUTIONS.

    PHASE 2.3 — Anteater API's /grades/aggregate endpoint will populate
    a real grades.csv. For most real-data courses, mock lookup returns
    None (no key match) — expected during this transitional phase.
    """
    return GRADE_DISTRIBUTIONS.get((course_id or "").upper())
