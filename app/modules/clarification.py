"""
Clarification Module

Maps to SKILL.md: Step 2 — Minimal Necessary Clarification.

Priority order (per SKILL.md):
  1. Is the term clear?
  2. Is the major clear?
  3. Are selected/current courses clear?
  4. If recommending: what is the core goal?
  5. If time matters: what time slots are available?

Entity extraction is LLM-only — the legacy keyword fallback was
removed once the agent loop landed. The agent reads the raw message
through its own tools / system prompt, so a noisy pre-agent keyword
pass was both redundant and a source of false positives.
"""


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


async def extract_info_from_message(message: str) -> dict:
    """
    Extract key fields from a user message via the LLM. Returns an
    empty dict if the LLM is unavailable or has nothing useful — the
    agent loop can still answer correctly from the raw message.
    """
    from app.llm.adapter import extract_info_llm

    llm_result = await extract_info_llm(message)
    if not llm_result:
        return {}

    updates = {}
    for field in _FORWARDED_FIELDS:
        v = llm_result.get(field)
        if v in (None, "", []):
            continue
        updates[field] = v
    return updates
