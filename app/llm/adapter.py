"""
LLM Adapter — Claude via Anthropic SDK (Option B: backend integration)

Three public functions:
  1. classify_intent_llm()  — intent + entity extraction in one call
  2. extract_info_llm()     — structured field extraction from user message
  3. generate_answer_llm()  — natural-language answer following SKILL.md structure

Graceful degradation: if ANTHROPIC_API_KEY is not set, LLM_ENABLED = False
and callers fall back to rule-based logic. Nothing breaks.
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────

LLM_MODEL = "claude-sonnet-4-20250514"  # Fast + capable; swap to opus-4-6 for production
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_ENABLED = bool(ANTHROPIC_API_KEY)

_client = None


def _get_client():
    """Lazy-init the Anthropic client."""
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ── System Prompts ───────────────────────────────────────

INTENT_SYSTEM_PROMPT = """\
You are an intent classifier for a UCI course recommendation assistant.

Given a user message, determine:
1. intent — one of: "course_recommendation", "single_query", "off_topic"
2. entities — any course IDs, professor names, terms, majors, or preferences mentioned

Definitions:
- "course_recommendation": user wants course suggestions, comparisons, schedule \
planning, or personalized advice
- "single_query": user asks a specific factual question about ONE course or ONE \
professor (prereqs, rating, GE status, conflict check)
- "off_topic": question is unrelated to courses — weather, food, clubs, career \
advice, study tips, or technical/programming questions about building systems

If the user is clearly in a course-selection context and asks about courses, \
professors, time, prereqs, scheduling, or recommendations, classify as \
course-related even without the word "recommend."

Respond with ONLY a JSON object, no markdown fences:
{"intent": "...", "confidence": 0.0-1.0, "entities": {"course_ids": [], \
"professor_names": [], "term": null, "major": null, \
"difficulty_preference": null, "recommendation_goal": null}}
"""

EXTRACTION_SYSTEM_PROMPT = """\
You are an entity extractor for a UCI course advisor. Extract structured info \
from the user message.

Return ONLY a JSON object with these fields (use null for anything not mentioned):
{
  "term": "Fall 2025" | "Winter 2026" | etc. | null,
  "major": "Computer Science" | "Informatics" | "Data Science" | etc. | null,
  "difficulty_preference": "easy" | "hard" | null,
  "recommendation_goal": "major_requirement" | "easy_gpa" | "professor_quality" \
| "ge_fulfillment" | null,
  "course_ids": ["ICS33", ...] | [],
  "professor_names": ["Thornton", ...] | []
}

Only extract what the user explicitly states or clearly implies. Do not guess.
"""

ANSWER_SYSTEM_PROMPT = """\
You are a UCI course advisor chatbot. You speak naturally, like a knowledgeable \
upperclassman who genuinely wants to help — not like a database printout.

You will receive:
- The student's message
- Their profile (major, year, completed/selected courses)
- Retrieved course data with sections, professor ratings, grade distributions, \
and prerequisite status

Your answer MUST follow this structure:
1. **Conclusion first** — directly state your top 1–3 recommendations
2. **Reasons** — 1–3 sentences per pick explaining why it fits
3. **Risk warnings** — unmet prereqs, time conflicts, heavy workload
4. **Alternatives** — if top picks have issues, suggest a safer backup
5. **Follow-up questions** — end with 2–3 natural suggestions for what to explore next

Style rules:
- Be direct, practical, conversational
- Convert raw data into judgments ("historically generous grading" not "avg GPA 3.4")
- If info is incomplete, say what your advice is based on
- If no results match, suggest loosening which specific constraints
- For single-point queries (one course or one professor), answer concisely — \
don't expand into a full recommendation flow
- Use **bold** for course IDs and key headers
- Keep your response focused — aim for clarity over length
"""


# ── Core LLM call ────────────────────────────────────────

async def _call_llm(system: str, user_content: str, max_tokens: int = 1024) -> str:
    """
    Single LLM call. Returns text. Raises on API errors so callers can fall back.

    Uses the sync Anthropic client inside async context — acceptable for a demo.
    For production, switch to anthropic.AsyncAnthropic.
    """
    client = _get_client()
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text


def _parse_json_response(text: str) -> Optional[dict]:
    """Parse JSON from LLM response, stripping markdown fences if present."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM returned unparseable JSON: %s", text[:200])
        return None


# ── Public API ───────────────────────────────────────────

async def classify_intent_llm(user_message: str) -> Optional[dict]:
    """
    Classify intent and extract entities in one call.

    Returns:
        {"intent": str, "confidence": float, "entities": {...}}
        or None on failure (caller falls back to rule-based).
    """
    if not LLM_ENABLED:
        return None
    try:
        raw = await _call_llm(INTENT_SYSTEM_PROMPT, user_message, max_tokens=256)
        result = _parse_json_response(raw)
        if result and "intent" in result:
            return result
        return None
    except Exception as e:
        logger.error("classify_intent_llm failed: %s", e)
        return None


async def extract_info_llm(user_message: str) -> Optional[dict]:
    """
    Extract structured fields from a user message.

    Returns:
        {"term": ..., "major": ..., "difficulty_preference": ..., ...}
        or None on failure (caller falls back to keyword extraction).
    """
    if not LLM_ENABLED:
        return None
    try:
        raw = await _call_llm(EXTRACTION_SYSTEM_PROMPT, user_message, max_tokens=256)
        return _parse_json_response(raw)
    except Exception as e:
        logger.error("extract_info_llm failed: %s", e)
        return None


async def generate_answer_llm(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
) -> Optional[str]:
    """
    Generate a natural-language answer from retrieved course data.

    Returns the formatted answer string, or None on failure
    (caller falls back to template-based answer).
    """
    if not LLM_ENABLED:
        return None
    try:
        context = _build_answer_context(user_message, retrieved_data, session_state)
        raw = await _call_llm(ANSWER_SYSTEM_PROMPT, context, max_tokens=1024)
        return raw.strip()
    except Exception as e:
        logger.error("generate_answer_llm failed: %s", e)
        return None


# ── Internal helpers ─────────────────────────────────────

def _build_answer_context(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
) -> str:
    """
    Assemble the user-turn content sent to the answer-generation LLM.
    Packs the student question, profile, and all retrieved data into one string.
    """
    parts = []

    parts.append(f"STUDENT MESSAGE: {user_message}")
    parts.append("")

    parts.append("STUDENT PROFILE:")
    parts.append(f"  Major: {session_state.get('major', 'unknown')}")
    parts.append(f"  Year: {session_state.get('year', 'unknown')}")
    parts.append(f"  Term: {session_state.get('term', 'unknown')}")
    completed = session_state.get("completed_courses", [])
    selected = session_state.get("selected_courses", [])
    parts.append(f"  Completed: {', '.join(completed) if completed else 'none listed'}")
    parts.append(f"  Enrolled: {', '.join(selected) if selected else 'none listed'}")
    goal = session_state.get("recommendation_goal")
    if goal:
        parts.append(f"  Goal: {goal}")
    diff = session_state.get("difficulty_preference")
    if diff:
        parts.append(f"  Difficulty preference: {diff}")
    parts.append("")

    parts.append("RETRIEVED COURSE DATA:")
    parts.append(json.dumps(retrieved_data, indent=2, default=str))

    return "\n".join(parts)
