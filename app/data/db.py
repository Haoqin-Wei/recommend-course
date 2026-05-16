"""
Database Access Layer — Interface & Mock Implementation

This module defines the interface for all data access needed by the
recommendation engine. The current implementation returns mock data.

TODO: Replace mock implementations with real database queries.
Suggested migration path:
  1. SQLite for local dev
  2. PostgreSQL for production
  3. Keep the same interface; only change the internals
"""

from typing import Optional
from app.data.mock_data import (
    COURSES,
    SECTIONS,
    PROFESSOR_RATINGS,
    GRADE_DISTRIBUTIONS,
    DEMO_STUDENT,
)


# ── Student Profile ──────────────────────────────────────

def get_student_profile(student_id: str) -> Optional[dict]:
    """
    Retrieve student profile: major, year, completed courses, selected courses.
    TODO: Query real student database.
    """
    if student_id == DEMO_STUDENT["student_id"]:
        return DEMO_STUDENT
    return None


# ── Course Catalog ───────────────────────────────────────

def get_course_info(course_id: str) -> Optional[dict]:
    """
    Retrieve single course details by ID.
    TODO: Query course catalog database.
    """
    for c in COURSES:
        if c["course_id"].upper() == course_id.upper():
            return c
    return None


def search_courses(
    term: Optional[str] = None,
    department: Optional[str] = None,
    major_requirement: Optional[str] = None,
    ge_category: Optional[str] = None,
    exclude_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Search courses with optional filters.
    TODO: Replace with parameterized SQL query.
    """
    results = COURSES[:]
    if department:
        results = [c for c in results if c["department"].upper() == department.upper()]
    if major_requirement:
        results = [c for c in results if major_requirement in c["major_requirement"]]
    if ge_category:
        results = [c for c in results if c["ge_category"] == ge_category]
    if exclude_ids:
        upper_exclude = [x.upper() for x in exclude_ids]
        results = [c for c in results if c["course_id"].upper() not in upper_exclude]
    return results


# ── Sections & Schedule ──────────────────────────────────

def get_sections(course_id: str, term: Optional[str] = None) -> list[dict]:
    """
    Get available sections for a course, optionally filtered by term.
    TODO: Query schedule database.
    """
    results = [s for s in SECTIONS if s["course_id"].upper() == course_id.upper()]
    if term:
        results = [s for s in results if s["term"] == term]
    return results


def get_schedule_for_student(student_id: str, term: str) -> list[dict]:
    """
    Return the student's current schedule (sections they are enrolled in).
    TODO: Query enrollment database.
    """
    profile = get_student_profile(student_id)
    if not profile:
        return []
    enrolled_ids = [c.upper() for c in profile.get("selected_courses", [])]
    return [s for s in SECTIONS if s["course_id"].upper() in enrolled_ids and s["term"] == term]


# ── Prerequisites ────────────────────────────────────────

def get_prerequisites(course_id: str) -> list[str]:
    """
    Return list of prerequisite course IDs for a given course.
    TODO: Query prerequisite graph database.
    """
    course = get_course_info(course_id)
    if course:
        return course.get("prerequisites", [])
    return []


def check_prerequisites_met(
    course_id: str,
    completed_courses: list[str],
    in_progress_courses: Optional[list[str]] = None,
) -> dict:
    """
    Check if a student meets the prerequisites for a course.

    Both completed_courses AND in_progress_courses count toward
    satisfying prereqs. Rationale: for next-term planning, a student
    currently enrolled in ICS33 will have completed it by the start
    of the term they're planning, so it should count as a satisfied
    prereq for any course that lists ICS33 as a dependency.

    The in_progress_courses parameter is optional for back-compat
    with older callers that pass only two positional args.

    Returns {"met": bool, "missing": [str]}
    """
    prereqs = get_prerequisites(course_id)
    satisfied: set[str] = {c.upper() for c in (completed_courses or [])}
    satisfied.update(c.upper() for c in (in_progress_courses or []))
    missing = [p for p in prereqs if p.upper() not in satisfied]
    return {"met": len(missing) == 0, "missing": missing}


# ── Professor Ratings ────────────────────────────────────

def get_professor_rating(instructor_name: str) -> Optional[dict]:
    """
    Retrieve RMP-style professor rating data.
    TODO: Query professor rating database or external API.
    """
    return PROFESSOR_RATINGS.get(instructor_name)


# ── Grade Distribution ───────────────────────────────────

def get_grade_distribution(course_id: str) -> Optional[dict]:
    """
    Retrieve historical grade distribution for a course.

    Live-fetches from UCI's Anteater API (with on-disk caching). See
    app/data/grades.py for endpoint and cache details.

    Falls back to the legacy mock_data.GRADE_DISTRIBUTIONS table if
    the API call fails or returns no data — keeps the demo working
    even when offline / API key not set / unknown course.
    """
    # Import lazily to avoid pulling `requests` into every import path.
    from app.data import grades as grades_module

    real = grades_module.get_grade_distribution(course_id)
    if real:
        return real

    # Fallback: legacy mock entry (preserves the few hand-curated CS
    # courses in mock_data.py until full migration).
    return GRADE_DISTRIBUTIONS.get(course_id.upper())
