"""
Tool definitions exposed to the agent loop.

Each tool is two things:
  1. A JSON schema entry in TOOL_SCHEMAS (sent to the LLM via the
     OpenAI-compatible `tools=[]` parameter).
  2. A Python dispatcher in DISPATCH that the loop calls.

Dispatchers thinly wrap `app.data.db`. db.py is the layer that does
DB-first → API-fallback → {found, source, reason}; tools just pass
results back to the LLM. Term-strict: tools that read term-scoped
data require a `term` argument from the model; if the model forgets,
we inject the student's currently-selected term from the tool
context as a safety net so we never silently return data from the
wrong term.

`dispatch(name, args, context)` is the single entry point. `context`
carries per-request state: user_id + selected term.
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
                "level, school, description, prerequisite text). "
                "Term-agnostic — returns the course as it exists in "
                "the catalog regardless of when it's offered."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {
                        "type": "string",
                        "description": "Course code in any common form: 'CS122A', 'COMPSCI 122A', 'ICS33'.",
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
                "List sections of a course in a SPECIFIC term: section "
                "code, lecture/discussion type, days, time, location, "
                "instructors, capacity, enrolled count, seats_open. "
                "ALWAYS pass `term` — never assume the term from "
                "context. Returns sections=[] with found=false if the "
                "course isn't offered that term."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "term": {
                        "type": "string",
                        "description": "Required. Form: 'Spring 2026', 'Fall 2026', 'Spring 2025'.",
                    },
                },
                "required": ["course_id", "term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_grade_distribution",
            "description": (
                "Historical grade distribution for a course (A/B/C "
                "percentages + average GPA), aggregated across all "
                "past offerings. Use when the student asks about "
                "difficulty, GPA impact, or 'is this an easy class'."
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
                "RateMyProfessor-style rating for an instructor: "
                "avg_rating (1-5), avg_difficulty, would_take_again_pct, "
                "num_ratings, plus a Steam-style `tier` block:\n"
                "  - mostly_positive (好评如潮) — avg_rating ≥ 4.2 AND ≥10 ratings\n"
                "  - mostly_negative (差评如潮) — avg_rating ≤ 2.5 AND ≥10 ratings\n"
                "  - mixed (褒贬不一) — anything in between\n"
                "  - insufficient_data (样本不足) — fewer than 5 ratings\n"
                "  - unrated (暂无评分) — not on RMP\n"
                "DB-first (local RMP snapshot), falls back to Anteater for "
                "instructors without RMP coverage. Use the tier label when "
                "summarizing — don't restate the raw number unless asked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instructor_name": {
                        "type": "string",
                        "description": (
                            "'LASTNAME, F.' (the form sections.csv uses), "
                            "'First Last', or a ucinetid like 'thornton'."
                        ),
                    },
                    "department": {
                        "type": "string",
                        "description": (
                            "UCI dept code from the course the instructor "
                            "teaches ('COMPSCI', 'BIO SCI', 'PUBHLTH'). "
                            "ALWAYS pass this when you know the course "
                            "context — common surnames like 'LEE, J.' "
                            "won't resolve without it."
                        ),
                    },
                },
                "required": ["instructor_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_professor_reviews",
            "description": (
                "Top student reviews (comments + per-review ratings + grade) "
                "for an instructor, optionally filtered to a specific course. "
                "Sorted by community thumbs-up then recency. Use this when the "
                "student wants qualitative detail beyond the tier — what's it "
                "like to take this professor, are exams fair, etc. Local-only; "
                "missing instructors return found=false."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instructor_name": {
                        "type": "string",
                        "description": "'LASTNAME, F.', 'First Last', or ucinetid.",
                    },
                    "course": {
                        "type": "string",
                        "description": (
                            "Optional course filter — pass '122A' or 'CS122A' "
                            "to restrict to that course's reviews."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of reviews to return (1-20, default 5).",
                    },
                    "department": {
                        "type": "string",
                        "description": (
                            "UCI dept code from the course context — "
                            "pass when known to disambiguate common surnames."
                        ),
                    },
                },
                "required": ["instructor_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_professor_reviews",
            "description": (
                "LLM-distilled structured summary of an instructor's "
                "student reviews — strengths/weaknesses, best_for/"
                "avoid_if descriptions, workload, exam_style, grading_"
                "style, teaching_style. Use this when you need to "
                "CHARACTERIZE a professor in depth (口碑 / 风格 / "
                "适合什么样的学生), NOT for short factual queries "
                "where the tier label from get_professor_rating "
                "suffices. Cache-first per (instructor, course) — first "
                "call costs ~1s, repeats are free. Returns English "
                "fields regardless of conversation language; translate "
                "as needed when quoting to the student."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instructor_name": {
                        "type": "string",
                        "description": "'LASTNAME, F.', 'First Last', or ucinetid.",
                    },
                    "course": {
                        "type": "string",
                        "description": (
                            "Optional course filter ('122A', 'CS122A'). "
                            "Pass it when the student is asking about a "
                            "specific class; omit for an all-courses "
                            "career summary."
                        ),
                    },
                    "department": {
                        "type": "string",
                        "description": (
                            "UCI dept code from the course context — "
                            "pass when known to disambiguate common surnames."
                        ),
                    },
                },
                "required": ["instructor_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_professor_tags",
            "description": (
                "Aggregated RMP tags students applied to this instructor "
                "(e.g. 'Tough grader', 'Caring', 'Test heavy', 'Amazing "
                "lectures') with counts. Cheaper than fetching full reviews "
                "when you only need a high-level vibe check."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instructor_name": {
                        "type": "string",
                        "description": "'LASTNAME, F.', 'First Last', or ucinetid.",
                    },
                    "course": {
                        "type": "string",
                        "description": "Optional course filter, e.g. '122A'.",
                    },
                    "department": {
                        "type": "string",
                        "description": (
                            "UCI dept code from the course context — "
                            "pass when known to disambiguate common surnames."
                        ),
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
                "prerequisites. Uses the student's recorded completed "
                "+ in-progress courses automatically — don't pass them "
                "unless you want to test a hypothetical scenario. "
                "Note: v1 treats prereqs as a flat list (AND), not an "
                "OR-tree, so 'missing' may overstate the gap when the "
                "real requirement is 'A OR B'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "string"},
                    "completed_courses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional override; omit to use the student's actual completed list.",
                    },
                    "in_progress_courses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional override; omit to use the student's actual current enrollment.",
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
                "List courses offered in a specific term, optionally "
                "filtered by department or GE category. Returns "
                "{course_id} entries only — call get_course_info on "
                "any candidate to get title/units/description. "
                "DB-only (no API fallback) — Anteater has no "
                "multi-criteria search endpoint."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "Required. e.g. 'Spring 2026'.",
                    },
                    "department": {
                        "type": "string",
                        "description": "Canonical UCI department code: 'COMPSCI', 'I&C SCI', 'MATH', 'STATS'.",
                    },
                    "ge_category": {
                        "type": "string",
                        "description": "GE category like 'III', 'IV', 'VII'.",
                    },
                    "exclude_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Course IDs to filter out (e.g. courses the student already took).",
                    },
                },
                "required": ["term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_section_conflict",
            "description": (
                "For every section pair of course_a × course_b in the "
                "given term, report whether their meeting times "
                "overlap. any_compatible_combination=true means the "
                "student CAN take both, just has to pick the right "
                "sections."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_a": {"type": "string"},
                    "course_b": {"type": "string"},
                    "term": {
                        "type": "string",
                        "description": "Required. e.g. 'Spring 2026'.",
                    },
                },
                "required": ["course_a", "course_b", "term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_student_profile",
            "description": (
                "Full persistent profile for the current student. "
                "Identity basics (major, year, completed, currently "
                "enrolled, term) are already in your system context, "
                "but call this when you need anything else recorded "
                "in their profile, plus their preferences."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_policy",
            "description": (
                "Look up an official UCI academic policy. Use this "
                "when the student's question depends on institutional "
                "rules (unit caps, graduation requirements, P/NP "
                "limits, quarter dates, etc.) rather than course data. "
                "Returns the policy data plus a source URL to cite. "
                "Call with no topic to list available topics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": [
                            "unit_limits",
                            "degree_requirements",
                            "class_level",
                            "pass_no_pass",
                            "academic_calendar",
                            "sources",
                        ],
                        "description": (
                            "unit_limits: min/max units per quarter (undergrad + grad, "
                            "ICS petition limits, summer session). "
                            "degree_requirements: 180 units, 2.0 GPA, residency. "
                            "class_level: unit thresholds for freshman/sophomore/junior/senior. "
                            "pass_no_pass: P/NP grading caps. "
                            "academic_calendar: quarter begin/end + instruction dates. "
                            "sources: official URLs for citation."
                        ),
                    },
                },
            },
        },
    },
]


# ══════════════════════════════════════════════════════════
#  Dispatchers — thin wrappers around db.py
# ══════════════════════════════════════════════════════════

def _tool_get_course_info(course_id: str) -> dict:
    return db.get_course_info(course_id)


def _tool_get_sections(
    course_id: str,
    *,
    context: dict,
    term: Optional[str] = None,
) -> dict:
    # Safety net: if the model forgot to pass term, fall back to the
    # session's selected term rather than returning unscoped data.
    effective_term = term or context.get("term")
    if not effective_term:
        return {"found": False, "source": "none", "sections": [],
                "reason": "term is required and no term was provided"}
    return db.get_sections(course_id, effective_term)


def _tool_get_grade_distribution(course_id: str) -> dict:
    return db.get_grade_distribution(course_id)


def _tool_get_professor_rating(
    instructor_name: str,
    department: Optional[str] = None,
) -> dict:
    return db.get_professor_rating(instructor_name, department=department)


def _tool_get_professor_reviews(
    instructor_name: str,
    course: Optional[str] = None,
    limit: int = 5,
    department: Optional[str] = None,
) -> dict:
    return db.get_professor_reviews(
        instructor_name, course=course, limit=limit, department=department,
    )


def _tool_get_professor_tags(
    instructor_name: str,
    course: Optional[str] = None,
    department: Optional[str] = None,
) -> dict:
    return db.get_professor_tags(instructor_name, course=course, department=department)


# Async tool: dispatch returns the coroutine; the agent loop awaits it.
def _tool_summarize_professor_reviews(
    instructor_name: str,
    course: Optional[str] = None,
    department: Optional[str] = None,
):
    return db.get_professor_summary(
        instructor_name, course=course, department=department,
    )


def _tool_check_prerequisites_met(
    course_id: str,
    *,
    context: dict,
    completed_courses: Optional[list[str]] = None,
    in_progress_courses: Optional[list[str]] = None,
) -> dict:
    # Default to the student's actual lists if the model didn't pass them.
    if completed_courses is None or in_progress_courses is None:
        prof = db.get_student_profile(context.get("user_id", ""))
        if prof.get("found"):
            p = prof["profile"]
            if completed_courses is None:
                completed_courses = p.get("completed_courses", [])
            if in_progress_courses is None:
                in_progress_courses = p.get("selected_courses", [])
    return db.check_prerequisites_met(
        course_id,
        completed_courses=completed_courses or [],
        in_progress_courses=in_progress_courses or [],
    )


def _tool_search_courses(
    *,
    context: dict,
    term: Optional[str] = None,
    department: Optional[str] = None,
    ge_category: Optional[str] = None,
    exclude_ids: Optional[list[str]] = None,
) -> dict:
    effective_term = term or context.get("term")
    if not effective_term:
        return {"found": False, "source": "none", "courses": [],
                "reason": "term is required and no term was provided"}
    return db.search_courses(
        term=effective_term,
        department=department,
        ge_category=ge_category,
        exclude_ids=exclude_ids,
    )


# ── Section conflict: real time-overlap detection ────────

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
            i += 1
    return out


def _parse_time(s: str) -> tuple[int, int]:
    """'11:00' or '11:00-12:20' → (start_min, end_min). For single
    times pass both halves separately and call this twice."""
    h, m = s.strip().split(":")
    return int(h), int(m)


def _section_overlap(a: dict, b: dict) -> bool:
    """True iff the two section dicts (from db._section_record_to_dict
    or db._api_section_to_dict) share a meeting day AND time window."""
    days_a = _parse_days(a.get("days") or "")
    days_b = _parse_days(b.get("days") or "")
    if not (days_a & days_b):
        return False
    try:
        sah, sam = _parse_time(a.get("start_time") or "")
        eah, eam = _parse_time(a.get("end_time") or "")
        sbh, sbm = _parse_time(b.get("start_time") or "")
        ebh, ebm = _parse_time(b.get("end_time") or "")
    except (ValueError, AttributeError):
        return False
    sa, ea = sah * 60 + sam, eah * 60 + eam
    sb, eb = sbh * 60 + sbm, ebh * 60 + ebm
    return sa < eb and sb < ea


def _tool_check_section_conflict(
    course_a: str,
    course_b: str,
    *,
    context: dict,
    term: Optional[str] = None,
) -> dict:
    effective_term = term or context.get("term")
    if not effective_term:
        return {"found": False, "source": "none",
                "reason": "term is required and no term was provided"}

    a = db.get_sections(course_a, effective_term)
    b = db.get_sections(course_b, effective_term)
    if not a.get("found") or not a.get("sections"):
        return {"found": False, "source": a.get("source", "none"),
                "reason": a.get("reason", f"no sections for {course_a}")}
    if not b.get("found") or not b.get("sections"):
        return {"found": False, "source": b.get("source", "none"),
                "reason": b.get("reason", f"no sections for {course_b}")}

    pairs: list[dict] = []
    any_compatible = False
    for sa in a["sections"]:
        for sb in b["sections"]:
            overlap = _section_overlap(sa, sb)
            if not overlap:
                any_compatible = True
            pairs.append({
                "a_section": sa.get("section_code"),
                "a_meeting": sa.get("time_display"),
                "b_section": sb.get("section_code"),
                "b_meeting": sb.get("time_display"),
                "overlap":   overlap,
            })
    return {
        "found": True,
        "source": "computed",
        "term":   effective_term,
        "course_a": course_a,
        "course_b": course_b,
        "pairs":  pairs,
        "any_compatible_combination": any_compatible,
    }


# ── Policy lookup ────────────────────────────────────────

def _tool_get_policy(topic: Optional[str] = None) -> dict:
    """
    Return UCI policy data by topic. Topics map to constants in
    app.data.policies. Each response includes the source URL so the
    LLM can cite where the rule came from.

    Calling with no topic returns the list of available topics so the
    model can browse without guessing.
    """
    from app.data import policies as p

    # Topic → (data, source_key)
    registry: dict[str, tuple[object, str]] = {
        "unit_limits":          (p.UNIT_LIMITS,         "academic_regulations"),
        "degree_requirements":  (p.DEGREE_REQUIREMENTS, "bachelor_requirements"),
        "class_level":          (p.CLASS_LEVEL,         "academic_regulations"),
        "pass_no_pass":         (p.PASS_NO_PASS,        "academic_regulations"),
        "academic_calendar":    (p.ACADEMIC_CALENDAR,   "academic_calendar"),
        "sources":              (p.SOURCES,             "registrar_calendar"),
    }

    if not topic:
        return {
            "available_topics": sorted(registry.keys()),
            "hint": "Call again with topic=<name> to fetch that policy.",
        }

    if topic not in registry:
        return {
            "found": False,
            "reason": f"unknown policy topic {topic!r}",
            "available_topics": sorted(registry.keys()),
        }

    data, source_key = registry[topic]
    return {
        "found": True,
        "topic": topic,
        "data": data,
        "source": source_key,
        "source_url": p.SOURCES.get(source_key),
        "verified_at": "2026-05-19",
    }


def _tool_get_student_profile(*, context: dict) -> dict:
    user_id = context.get("user_id", "")
    result = db.get_student_profile(user_id)
    # Decorate with preferences from the memory layer (db doesn't
    # expose them directly because they're not catalog data).
    if result.get("found"):
        try:
            from app.memory import get_memory_manager
            mem = get_memory_manager()
            result["preferences"] = mem.get_preferences(user_id)
        except Exception as e:
            logger.debug("preferences enrichment skipped: %s", e)
    return result


DISPATCH: dict[str, Callable[..., dict]] = {
    "get_course_info":          _tool_get_course_info,
    "get_sections":             _tool_get_sections,
    "get_grade_distribution":   _tool_get_grade_distribution,
    "get_professor_rating":     _tool_get_professor_rating,
    "get_professor_reviews":    _tool_get_professor_reviews,
    "get_professor_tags":       _tool_get_professor_tags,
    "summarize_professor_reviews": _tool_summarize_professor_reviews,
    "check_prerequisites_met":  _tool_check_prerequisites_met,
    "search_courses":           _tool_search_courses,
    "check_section_conflict":   _tool_check_section_conflict,
    "get_student_profile":      _tool_get_student_profile,
    "get_policy":               _tool_get_policy,
}


# ══════════════════════════════════════════════════════════
#  Dispatch entry point
# ══════════════════════════════════════════════════════════

def dispatch(name: str, args: dict, *, context: dict):
    """Run a tool by name.

    Returns either a JSON-serializable dict (sync tools) or a
    coroutine that resolves to one (async tools like
    summarize_professor_reviews). The caller — typically the agent
    loop — is responsible for awaiting coroutine results.

    On synchronous failure, returns {"error": "..."} rather than
    raising. Async failures must be caught by the awaiter.
    """
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool: {name}"}
    try:
        sig = inspect.signature(fn)
        if "context" in sig.parameters:
            return fn(context=context, **(args or {}))
        return fn(**(args or {}))
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:
        logger.warning("tool %s failed: %s: %s", name, type(e).__name__, e)
        return {"error": f"{type(e).__name__}: {e}"}


def humanize_tool_call(name: str, args: dict) -> str:
    """Short user-facing label for a tool call (chip text)."""
    a = args or {}
    term_suffix = f" · {a['term']}" if a.get("term") else ""
    if name == "get_course_info":
        return f"查询 {a.get('course_id', '')} 课程信息"
    if name == "get_sections":
        return f"查询 {a.get('course_id', '')} 排课{term_suffix}"
    if name == "get_grade_distribution":
        return f"查询 {a.get('course_id', '')} 历年成绩"
    if name == "get_professor_rating":
        return f"查询教授 {a.get('instructor_name', '')}"
    if name == "get_professor_reviews":
        course = a.get("course")
        suffix = f" · {course}" if course else ""
        return f"读取学生评论 · {a.get('instructor_name', '')}{suffix}"
    if name == "get_professor_tags":
        return f"汇总教授标签 · {a.get('instructor_name', '')}"
    if name == "summarize_professor_reviews":
        course = a.get("course")
        suffix = f" · {course}" if course else ""
        return f"提炼教授口碑 · {a.get('instructor_name', '')}{suffix}"
    if name == "check_prerequisites_met":
        return f"检查 {a.get('course_id', '')} 先修要求"
    if name == "search_courses":
        bits = [v for v in (a.get("department"), a.get("ge_category")) if v]
        return f"搜索课程（{', '.join(bits) or '全部'}）{term_suffix}"
    if name == "check_section_conflict":
        return f"对比 {a.get('course_a', '')} 与 {a.get('course_b', '')} 时间冲突{term_suffix}"
    if name == "get_student_profile":
        return "读取学生画像"
    if name == "get_policy":
        topic = a.get("topic")
        return f"查询学校政策 · {topic}" if topic else "列出学校政策主题"
    return f"调用 {name}"
