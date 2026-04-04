"""
Query Module

Maps to SKILL.md: Step 3 — Search Knowledge Base.

Routes queries to the appropriate data layer functions based on
the type of question:
  - Course recommendation / filtering → search_courses
  - Professor comparison / RMP        → get_professor_rating
  - Difficulty / grade distribution    → get_grade_distribution
  - Prerequisite check                 → check_prerequisites_met
  - Time conflict / scheduling         → get_sections + conflict check
  - GE / major requirement             → search_courses with filters

Applies SKILL.md filtering rules:
  1. Exclude already-taken or enrolled courses
  2. Flag unmet prerequisites (don't include as primary recommendations)
  3. Flag courses that conflict with current schedule
  4. Apply user preferences (easy, high-rated professor, time slot)
"""

from typing import Optional
from app.data import db


def query_course_recommendations(
    term: str,
    major: Optional[str] = None,
    completed_courses: Optional[list[str]] = None,
    selected_courses: Optional[list[str]] = None,
    difficulty_preference: Optional[str] = None,
    recommendation_goal: Optional[str] = None,
) -> dict:
    """
    Main recommendation query. Returns structured results with
    primary recommendations, alternatives, and warnings.
    """
    completed = completed_courses or []
    selected = selected_courses or []
    exclude_ids = completed + selected

    # ── Fetch candidate courses ───────────────────────────
    if recommendation_goal == "ge_fulfillment":
        candidates = [c for c in db.search_courses(exclude_ids=exclude_ids) if c.get("ge_category")]
    elif recommendation_goal == "major_requirement" and major:
        candidates = db.search_courses(major_requirement=major, exclude_ids=exclude_ids)
    else:
        candidates = db.search_courses(exclude_ids=exclude_ids)

    # ── Enrich each candidate ─────────────────────────────
    enriched = []
    for course in candidates:
        cid = course["course_id"]

        # Prerequisites check
        prereq_status = db.check_prerequisites_met(cid, completed)

        # Sections for the requested term
        sections = db.get_sections(cid, term)
        if not sections:
            continue  # No sections offered this term

        # Grade distribution
        grades = db.get_grade_distribution(cid)

        # Professor ratings for each section
        section_details = []
        for sec in sections:
            prof_rating = db.get_professor_rating(sec["instructor"])
            section_details.append({**sec, "professor_rating": prof_rating})

        # Time conflict check
        # TODO: Implement real time overlap detection
        has_conflict = False

        enriched.append({
            "course": course,
            "prereq_met": prereq_status["met"],
            "prereq_missing": prereq_status["missing"],
            "sections": section_details,
            "grade_distribution": grades,
            "has_conflict": has_conflict,
        })

    # ── Sort by preference ────────────────────────────────
    enriched = _sort_by_preference(enriched, difficulty_preference, recommendation_goal)

    # ── Separate primary vs flagged ───────────────────────
    primary = [e for e in enriched if e["prereq_met"] and not e["has_conflict"]]
    flagged = [e for e in enriched if not e["prereq_met"] or e["has_conflict"]]

    return {
        "primary": primary[:5],
        "flagged": flagged[:3],
        "total_found": len(enriched),
    }


def query_single_course(course_id: str, term: Optional[str] = None) -> Optional[dict]:
    """Retrieve full details for a single course."""
    course = db.get_course_info(course_id)
    if not course:
        return None

    sections = db.get_sections(course_id, term)
    grades = db.get_grade_distribution(course_id)
    prereqs = db.get_prerequisites(course_id)

    section_details = []
    for sec in sections:
        prof = db.get_professor_rating(sec["instructor"])
        section_details.append({**sec, "professor_rating": prof})

    return {
        "course": course,
        "sections": section_details,
        "grade_distribution": grades,
        "prerequisites": prereqs,
    }


def query_professor(instructor_name: str) -> Optional[dict]:
    """Retrieve professor rating details."""
    return db.get_professor_rating(instructor_name)


def check_schedule_conflict(
    course_id: str,
    student_id: str,
    term: str,
) -> dict:
    """
    Check if adding a course would conflict with the student's current schedule.
    TODO: Implement real time-overlap detection.
    """
    student_schedule = db.get_schedule_for_student(student_id, term)
    new_sections = db.get_sections(course_id, term)

    # Placeholder — always returns no conflict in demo
    return {
        "has_conflict": False,
        "conflicting_with": None,
        "message": "No conflicts detected (demo mode).",
    }


# ── Internal helpers ─────────────────────────────────────

def _sort_by_preference(
    enriched: list[dict],
    difficulty_pref: Optional[str],
    goal: Optional[str],
) -> list[dict]:
    """
    Sort candidates based on user preferences.
    TODO: Make scoring more sophisticated.
    """
    def score(item):
        s = 0
        grades = item.get("grade_distribution") or {}

        # Prefer higher avg GPA if user wants easy
        if difficulty_pref == "easy":
            s += grades.get("avg_gpa", 0) * 10

        # Prefer professor rating
        best_prof = 0
        for sec in item.get("sections", []):
            pr = sec.get("professor_rating") or {}
            overall = pr.get("overall") or 0
            best_prof = max(best_prof, overall)
        s += best_prof * 5

        # Bonus for major requirement match
        if goal == "major_requirement":
            s += 10 if item["course"]["major_requirement"] else 0

        return s

    enriched.sort(key=score, reverse=True)
    return enriched
