"""
Clarification Module

Maps to SKILL.md: Step 2 — Minimal Necessary Clarification.

Priority order (per SKILL.md):
  1. Is the term clear?
  2. Is the major clear?
  3. Are selected/current courses clear?
  4. If recommending: what is the core goal?
  5. If time matters: what time slots are available?
"""

import re
from typing import Optional


# Used by the keyword fallback to find course IDs in a message.
_COURSE_ID = re.compile(r'\b[A-Z][A-Z0-9]{1,7}\d+[A-Z]?\b', re.IGNORECASE)


def detect_missing_fields(session_state: dict, intent: str) -> list[dict]:
    missing = []

    if not session_state.get("term"):
        missing.append({
            "field": "term", "priority": 1,
            "question": "Which term are you looking at? (e.g., Fall 2025, Winter 2026)",
        })

    if not session_state.get("major"):
        missing.append({
            "field": "major", "priority": 2,
            "question": "What's your major? That'll help me find courses that count toward your requirements.",
        })

    if intent == "course_recommendation":
        if not session_state.get("selected_courses"):
            missing.append({
                "field": "selected_courses", "priority": 3,
                "question": "Do you have any courses already on your schedule? I can help avoid time conflicts.",
            })
        if not session_state.get("recommendation_goal"):
            missing.append({
                "field": "recommendation_goal", "priority": 4,
                "question": "What matters most to you — satisfying major requirements, finding easier courses, or getting a good professor?",
            })
        if not session_state.get("preferred_time"):
            missing.append({
                "field": "preferred_time", "priority": 5,
                "question": "Any time preferences? (e.g., mornings only, no Friday classes)",
            })

    missing.sort(key=lambda x: x["priority"])
    return missing


def needs_clarification(session_state: dict, intent: str) -> bool:
    if intent == "single_query":
        return False
    if not session_state.get("term") or not session_state.get("major"):
        return True
    return False


def build_clarification_response(missing_fields: list[dict], max_questions: int = 3) -> str:
    to_ask = missing_fields[:max_questions]
    if len(to_ask) == 1:
        return f"Before I can help, one quick question — {to_ask[0]['question']}"
    lines = ["I'd love to help! A few quick questions first:\n"]
    for i, item in enumerate(to_ask, 1):
        lines.append(f"{i}. {item['question']}")
    return "\n".join(lines)


# Fields the LLM extractor returns that we forward to the caller.
# Scalars: caught by update_session(). Lists: caught by chat._capture_hard_facts().
_FORWARDED_FIELDS = (
    # Scalars
    "term", "major", "year", "target_gpa", "graduation_term",
    "difficulty_preference", "recommendation_goal",
    # Lists
    "currently_taking", "completed",
)


async def extract_info_from_message(message: str, session_state: dict) -> dict:
    """
    Extract key fields from a user message.

    Strategy:
      1. Try LLM extraction (handles natural phrasing well, distinguishes
         "I'm taking X" vs "I took X" vs "tell me about X").
      2. Fall back to keyword matching if LLM is unavailable OR returns
         nothing useful — keyword fallback now also handles currently_taking
         and completed via simple verb-near-course-ID heuristics.
    """
    from app.llm.adapter import extract_info_llm

    llm_result = await extract_info_llm(message)
    if llm_result:
        updates = {}
        for field in _FORWARDED_FIELDS:
            v = llm_result.get(field)
            # Skip empty values (None, "", [], 0 — but keep target_gpa numerical 0... unlikely)
            if v in (None, "", []):
                continue
            updates[field] = v
        if updates:
            return updates
        # LLM returned a dict but no useful fields — fall through to keyword fallback

    return _extract_info_keyword(message)


def _extract_info_keyword(message: str) -> dict:
    """Keyword-based field extraction (used when LLM is unavailable or empty)."""
    updates = {}
    msg_lower = message.lower()

    # ── Term detection ────────────────────────────────────
    term_map = {
        "fall 2025": "Fall 2025", "fall 25": "Fall 2025",
        "winter 2026": "Winter 2026", "winter 26": "Winter 2026",
        "spring 2026": "Spring 2026", "spring 26": "Spring 2026",
        "fall 2026": "Fall 2026",
    }
    for key, val in term_map.items():
        if key in msg_lower:
            updates["term"] = val
            break

    # ── Major detection ───────────────────────────────────
    major_map = {
        "computer science": "Computer Science", "cs": "Computer Science",
        "compsci": "Computer Science",
        "informatics": "Informatics",
        "data science": "Data Science",
    }
    for key, val in major_map.items():
        if key in msg_lower:
            updates["major"] = val
            break

    # ── Difficulty / goal ─────────────────────────────────
    if any(w in msg_lower for w in ["easy", "chill", "light", "simple", "gpa boost"]):
        updates["difficulty_preference"] = "easy"
    elif any(w in msg_lower for w in ["challenging", "hard", "rigorous"]):
        updates["difficulty_preference"] = "hard"

    if any(w in msg_lower for w in ["major requirement", "satisfy requirement", "count toward"]):
        updates["recommendation_goal"] = "major_requirement"
    elif any(w in msg_lower for w in ["easy", "boost gpa", "light"]):
        updates["recommendation_goal"] = "easy_gpa"
    elif any(w in msg_lower for w in ["good professor", "best professor", "rmp", "rating"]):
        updates["recommendation_goal"] = "professor_quality"
    elif any(w in msg_lower for w in ["ge", "general education"]):
        updates["recommendation_goal"] = "ge_fulfillment"

    # ── Course-status detection (NEW) ─────────────────────
    # Walk every course-ID match. If a status verb appears within 30 chars
    # before the match, classify it. "I'm taking STAT67" → currently_taking.
    taking_verbs = ("taking", "in ", "currently in", "enrolled in", "正在上")
    completed_verbs = ("took", "passed", "finished", "completed", "已修过", "已修", "上过")

    for m in _COURSE_ID.finditer(message):
        cid = m.group().upper()
        start = max(0, m.start() - 30)
        before = msg_lower[start:m.start()]
        if any(v in before for v in taking_verbs):
            updates.setdefault("currently_taking", []).append(cid)
        elif any(v in before for v in completed_verbs):
            updates.setdefault("completed", []).append(cid)

    # Dedup the lists
    for k in ("currently_taking", "completed"):
        if k in updates:
            seen = set()
            deduped = []
            for c in updates[k]:
                if c not in seen:
                    seen.add(c)
                    deduped.append(c)
            updates[k] = deduped

    return updates
