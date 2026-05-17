"""
Tool definitions exposed to the agent loop.

Each tool is two things:
  1. A JSON schema entry in TOOL_SCHEMAS (sent to the LLM via the
     OpenAI-compatible `tools=[]` parameter). The schema teaches the
     model when and how to call the tool.
  2. A Python dispatcher in DISPATCH that the loop calls when the
     LLM emits a tool_call. Dispatchers wrap existing db.py / query.py
     functions — they add NO new business logic, only argument
     defaulting (e.g. pulling completed_courses from the student
     profile when the model didn't pass them) and uniform error
     handling (every tool returns a JSON-serializable dict, never
     raises).

`dispatch(name, args, context)` is the single entry point. `context`
carries per-request state — currently just `user_id` so dispatchers
that need the student profile can look it up themselves rather than
forcing the model to fetch it first and pass it in.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Optional

from app.data import db

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  JSON schemas — what the LLM sees
# ══════════════════════════════════════════════════════════

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_course_info",
            "description": (
                "Get a UCI course's catalog metadata (title, units, "
                "prerequisites, department, description). Returns "
                "found=false if the course ID is not in the catalog."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {
                        "type": "string",
                        "description": "Course code like 'CS122A', 'ICS46', 'STATS67'.",
                    },
                },
                "required": ["course_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sections",
            "description": (
                "List all scheduled sections of a course in a term: "
                "section letter, instructor, meeting days, time window, "
                "location, open seats. Empty list means no sections "
                "scheduled (the course may exist but not be offered)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "term": {
                        "type": "string",
                        "description": "Optional term like 'Fall 2025' or 'Spring 2026'. Omit to get all terms.",
                    },
                },
                "required": ["course_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_grade_distribution",
            "description": (
                "Historical grade distribution for a course from UCI's "
                "Anteater API: pct_A / pct_B / pct_C / avg_gpa. Use "
                "this when the student asks about difficulty, GPA "
                "impact, or 'is this an easy class'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"course_id": {"type": "string"}},
                "required": ["course_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_professor_rating",
            "description": (
                "RMP-style rating for an instructor: overall rating, "
                "difficulty, would-take-again %. Returns found=false "
                "for instructors not in the ratings table."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instructor_name": {
                        "type": "string",
                        "description": "Last-name-first form like 'Thornton, A.' or 'Pattis, R.'",
                    },
                },
                "required": ["instructor_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_prerequisites_met",
            "description": (
                "Check whether the student satisfies a course's "
                "prerequisites. Pulls completed_courses + "
                "selected_courses (in-progress) from the student "
                "profile automatically — don't pass them unless you "
                "want to test a hypothetical."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "completed_courses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional override. Omit to use the student's actual completed list.",
                    },
                    "in_progress_courses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional override. Omit to use the student's actual current enrollment.",
                    },
                },
                "required": ["course_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_courses",
            "description": (
                "Search the UCI catalog by department, GE category, "
                "or major requirement. Returns a list of {course_id, "
                "title, units, ...}. Use this when the student is "
                "looking for candidates ('recommend GE', 'CS electives'), "
                "not when they've named a specific course."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {
                        "type": "string",
                        "description": "Department code, e.g. 'CS', 'ICS', 'ANTHRO'.",
                    },
                    "ge_category": {
                        "type": "string",
                        "description": "GE category like 'III', 'IV', 'VII' (Roman numerals).",
                    },
                    "major_requirement": {
                        "type": "string",
                        "description": "Substring matched against a course's major_requirement tags.",
                    },
                    "term": {
                        "type": "string",
                        "description": "Optional term to restrict to courses offered that term.",
                    },
                    "exclude_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Course IDs to filter out (e.g. courses the student already took).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_section_conflict",
            "description": (
                "For every section-pair of course_a × course_b, "
                "report whether their meeting times overlap. Returns "
                "any_compatible_combination=true if at least one "
                "section pair has no conflict — meaning the student "
                "CAN take both, just has to pick the right sections."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_a": {"type": "string"},
                    "course_b": {"type": "string"},
                    "term": {
                        "type": "string",
                        "description": "Optional term filter, e.g. 'Spring 2026'. Omit to check all terms.",
                    },
                },
                "required": ["course_a", "course_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_student_profile",
            "description": (
                "Full persistent profile + preferences + facts + "
                "pinned decisions for the current student. The "
                "essentials (major, year, completed, currently "
                "enrolled, term) are already in your system context — "
                "use this tool to dig into preferences ('avoids early "
                "classes'), historical facts, or session decisions."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ══════════════════════════════════════════════════════════
#  Dispatchers — Python side
# ══════════════════════════════════════════════════════════

def _tool_get_course_info(course_id: str) -> dict:
    info = db.get_course_info(course_id)
    return {"course_id": course_id, "found": info is not None, "info": info}


def _tool_get_sections(course_id: str, term: Optional[str] = None) -> dict:
    sections = db.get_sections(course_id, term)
    return {
        "course_id": course_id,
        "term": term,
        "sections": sections,
        "count": len(sections),
    }


def _tool_get_grade_distribution(course_id: str) -> dict:
    grades = db.get_grade_distribution(course_id)
    return {"course_id": course_id, "found": grades is not None, "grades": grades}


def _tool_get_professor_rating(instructor_name: str) -> dict:
    rating = db.get_professor_rating(instructor_name)
    return {"instructor_name": instructor_name, "found": rating is not None, "rating": rating}


def _tool_check_prerequisites_met(
    course_id: str,
    *,
    context: dict,
    completed_courses: Optional[list[str]] = None,
    in_progress_courses: Optional[list[str]] = None,
) -> dict:
    # Default to the student's actual lists from their profile so the
    # model doesn't have to remember to fetch the profile first.
    if completed_courses is None or in_progress_courses is None:
        profile = db.get_student_profile(context.get("user_id", ""))
        if profile:
            if completed_courses is None:
                completed_courses = profile.get("completed_courses", [])
            if in_progress_courses is None:
                in_progress_courses = profile.get("selected_courses", [])
    result = db.check_prerequisites_met(
        course_id,
        completed_courses or [],
        in_progress_courses or [],
    )
    return {"course_id": course_id, **result}


def _tool_search_courses(
    department: Optional[str] = None,
    ge_category: Optional[str] = None,
    major_requirement: Optional[str] = None,
    term: Optional[str] = None,
    exclude_ids: Optional[list[str]] = None,
) -> dict:
    results = db.search_courses(
        term=term,
        department=department,
        major_requirement=major_requirement,
        ge_category=ge_category,
        exclude_ids=exclude_ids,
    )
    # Cap result count — catalog has 6700 courses; an unfiltered call
    # would blow the LLM's token budget.
    capped = results[:30]
    return {
        "filters": {
            "department": department,
            "ge_category": ge_category,
            "major_requirement": major_requirement,
            "term": term,
            "exclude_ids": exclude_ids,
        },
        "courses": capped,
        "total_found": len(results),
        "truncated": len(results) > 30,
    }


# ── check_section_conflict: real time-overlap detection ───

def _parse_days(s: str) -> set[str]:
    """'MWF' → {M,W,F}; 'TuTh' → {Tu,Th}; 'MTuWThF' → all five."""
    out: set[str] = set()
    i = 0
    while i < len(s):
        if s[i : i + 2] in ("Tu", "Th"):
            out.add(s[i : i + 2])
            i += 2
        elif s[i] in ("M", "W", "F", "S", "U"):
            out.add(s[i])
            i += 1
        else:
            i += 1  # skip whitespace / punctuation
    return out


def _parse_time(s: str) -> tuple[int, int]:
    """'10:00-10:50' → (600, 650), minutes since midnight."""
    start, end = s.split("-")

    def to_min(t: str) -> int:
        h, m = t.strip().split(":")
        return int(h) * 60 + int(m)

    return to_min(start), to_min(end)


def _sections_overlap(a: dict, b: dict) -> bool:
    days_a, days_b = _parse_days(a.get("days", "")), _parse_days(b.get("days", ""))
    if not (days_a & days_b):
        return False
    try:
        sa, ea = _parse_time(a.get("time", ""))
        sb, eb = _parse_time(b.get("time", ""))
    except (ValueError, AttributeError):
        return False  # missing/malformed time → assume no overlap
    return sa < eb and sb < ea


def _tool_check_section_conflict(
    course_a: str,
    course_b: str,
    term: Optional[str] = None,
) -> dict:
    secs_a = db.get_sections(course_a, term)
    secs_b = db.get_sections(course_b, term)
    if not secs_a:
        return {"error": f"no sections found for {course_a}" + (f" in {term}" if term else "")}
    if not secs_b:
        return {"error": f"no sections found for {course_b}" + (f" in {term}" if term else "")}

    pairs: list[dict] = []
    any_compatible = False
    for sa in secs_a:
        for sb in secs_b:
            overlap = _sections_overlap(sa, sb)
            if not overlap:
                any_compatible = True
            pairs.append({
                "a_section": sa.get("section"),
                "a_meeting": f"{sa.get('days', '?')} {sa.get('time', '?')}",
                "b_section": sb.get("section"),
                "b_meeting": f"{sb.get('days', '?')} {sb.get('time', '?')}",
                "overlap": overlap,
            })
    return {
        "course_a": course_a,
        "course_b": course_b,
        "term": term,
        "pairs": pairs,
        "any_compatible_combination": any_compatible,
    }


def _tool_get_student_profile(*, context: dict) -> dict:
    user_id = context.get("user_id", "")
    profile = db.get_student_profile(user_id)
    # Decorate with preferences from the memory provider. The memory
    # layer doesn't expose a facts getter today (facts get folded into
    # the system-prompt block via prefetch); preferences are richer
    # because the LLM might want to ground a recommendation in them.
    extras: dict[str, Any] = {}
    try:
        from app.memory import get_memory_manager

        mem = get_memory_manager()
        extras["preferences"] = mem.get_preferences(user_id)
    except Exception as e:
        logger.debug("profile-preferences enrichment skipped: %s", e)
    return {"user_id": user_id, "profile": profile, **extras}


DISPATCH: dict[str, Callable[..., dict]] = {
    "get_course_info":          _tool_get_course_info,
    "get_sections":             _tool_get_sections,
    "get_grade_distribution":   _tool_get_grade_distribution,
    "get_professor_rating":     _tool_get_professor_rating,
    "check_prerequisites_met":  _tool_check_prerequisites_met,
    "search_courses":           _tool_search_courses,
    "check_section_conflict":   _tool_check_section_conflict,
    "get_student_profile":      _tool_get_student_profile,
}


# ══════════════════════════════════════════════════════════
#  Dispatch entry point
# ══════════════════════════════════════════════════════════

def dispatch(name: str, args: dict, *, context: dict) -> dict:
    """
    Execute a tool by name. Always returns a JSON-serializable dict;
    on any error returns {"error": "...message..."} instead of
    raising. `context` carries per-request state (currently user_id).
    """
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool: {name}"}
    try:
        sig = inspect.signature(fn)
        # Only inject context for tools that declare it as a parameter.
        if "context" in sig.parameters:
            return fn(context=context, **(args or {}))
        return fn(**(args or {}))
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:
        logger.warning("tool %s failed: %s: %s", name, type(e).__name__, e)
        return {"error": f"{type(e).__name__}: {e}"}


def humanize_tool_call(name: str, args: dict) -> str:
    """
    Short human-readable label for a tool call, shown to the user as
    a status chip ('查询 CS122A sections...'). Falls back to a generic
    label if the tool name isn't recognized.
    """
    a = args or {}
    if name == "get_course_info":
        return f"查询 {a.get('course_id', '')} 课程信息"
    if name == "get_sections":
        return f"查询 {a.get('course_id', '')} 排课时间"
    if name == "get_grade_distribution":
        return f"查询 {a.get('course_id', '')} 历年成绩分布"
    if name == "get_professor_rating":
        return f"查询教授 {a.get('instructor_name', '')} 评价"
    if name == "check_prerequisites_met":
        return f"检查 {a.get('course_id', '')} 先修要求"
    if name == "search_courses":
        bits = [v for v in (a.get("major"), a.get("level"), a.get("keyword")) if v]
        return f"搜索课程（{', '.join(bits) or '全部'}）"
    if name == "check_section_conflict":
        return f"对比 {a.get('course_a', '')} 与 {a.get('course_b', '')} 时间冲突"
    if name == "get_student_profile":
        return "读取学生画像"
    return f"调用 {name}"
