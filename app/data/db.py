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


def check_prerequisites_met(course_id: str, completed_courses: list[str]) -> dict:
    """
    Check if a student meets the prerequisites for a course.
    Returns {"met": bool, "missing": [str]}
    TODO: Handle complex prerequisite logic (AND/OR trees).
    """
    prereqs = get_prerequisites(course_id)
    completed_upper = [c.upper() for c in completed_courses]
    missing = [p for p in prereqs if p.upper() not in completed_upper]
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
    TODO: Query grade distribution database.
    """
    return GRADE_DISTRIBUTIONS.get(course_id.upper())
