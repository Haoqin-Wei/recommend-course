"""
Clarification Module

Maps to SKILL.md: Step 2 — Minimal Necessary Clarification.

Priority order (per SKILL.md):
  1. Is the term clear?
  2. Is the major clear?
  3. Are selected/current courses clear?
  4. If recommending: what is the core goal?
  5. If time matters: what time slots are available?

Rules:
  - Ask 1–3 critical missing items at a time, not all at once.
  - Use natural language, not field names.
  - If the question only needs a single fact lookup, skip clarification.
"""

from typing import Optional


def detect_missing_fields(
    session_state: dict,
    intent: str,
) -> list[dict]:
    """
    Given current session state and intent type, return a list of
    missing fields ordered by priority.

    Each item: {"field": str, "priority": int, "question": str}
    """
    missing = []

    if not session_state.get("term"):
        missing.append({
            "field": "term",
            "priority": 1,
            "question": "Which term are you looking at? (e.g., Fall 2025, Winter 2026)",
        })

    if not session_state.get("major"):
        missing.append({
            "field": "major",
            "priority": 2,
            "question": "What's your major? That'll help me find courses that count toward your requirements.",
        })

    if intent == "course_recommendation":
        if not session_state.get("selected_courses"):
            missing.append({
                "field": "selected_courses",
                "priority": 3,
                "question": "Do you have any courses already on your schedule? I can help avoid time conflicts.",
            })

        if not session_state.get("recommendation_goal"):
            missing.append({
                "field": "recommendation_goal",
                "priority": 4,
                "question": "What matters most to you — satisfying major requirements, finding easier courses, or getting a good professor?",
            })

        if not session_state.get("preferred_time"):
            # Only ask if the question involves scheduling
            missing.append({
                "field": "preferred_time",
                "priority": 5,
                "question": "Any time preferences? (e.g., mornings only, no Friday classes)",
            })

    # Sort by priority, return top items
    missing.sort(key=lambda x: x["priority"])
    return missing


def needs_clarification(session_state: dict, intent: str) -> bool:
    """
    Check if we have enough info to proceed.
    For single_query intent, we usually don't need full profile.
    For course_recommendation, we need at least term + major.
    """
    if intent == "single_query":
        return False  # Single-point queries can proceed without full profile

    # For recommendations, require at least term and major
    if not session_state.get("term") or not session_state.get("major"):
        return True

    return False


def build_clarification_response(missing_fields: list[dict], max_questions: int = 3) -> str:
    """
    Build a natural-language clarification message.
    Per SKILL.md: ask 1–3 critical items, natural tone.
    """
    to_ask = missing_fields[:max_questions]

    if len(to_ask) == 1:
        return f"Before I can help, one quick question — {to_ask[0]['question']}"

    lines = ["I'd love to help! A few quick questions first:\n"]
    for i, item in enumerate(to_ask, 1):
        lines.append(f"{i}. {item['question']}")

    return "\n".join(lines)


def extract_info_from_message(message: str, session_state: dict) -> dict:
    """
    Attempt to extract key fields from a user message.
    This is a simple keyword-based extractor for the demo.

    TODO: Replace with LLM-based extraction for production accuracy.
    """
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
        "computer science": "Computer Science",
        "cs": "Computer Science",
        "compsci": "Computer Science",
        "informatics": "Informatics",
        "data science": "Data Science",
    }
    for key, val in major_map.items():
        if key in msg_lower:
            updates["major"] = val
            break

    # ── Difficulty preference ─────────────────────────────
    if any(w in msg_lower for w in ["easy", "chill", "light", "simple", "gpa boost"]):
        updates["difficulty_preference"] = "easy"
    elif any(w in msg_lower for w in ["challenging", "hard", "rigorous"]):
        updates["difficulty_preference"] = "hard"

    # ── Goal detection ────────────────────────────────────
    if any(w in msg_lower for w in ["major requirement", "satisfy requirement", "count toward"]):
        updates["recommendation_goal"] = "major_requirement"
    elif any(w in msg_lower for w in ["easy", "boost gpa", "light"]):
        updates["recommendation_goal"] = "easy_gpa"
    elif any(w in msg_lower for w in ["good professor", "best professor", "rmp", "rating"]):
        updates["recommendation_goal"] = "professor_quality"
    elif any(w in msg_lower for w in ["ge", "general education"]):
        updates["recommendation_goal"] = "ge_fulfillment"

    return updates
