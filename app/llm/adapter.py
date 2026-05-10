"""
LLM Adapter — DeepSeek via OpenAI-compatible SDK

Public functions:
  1. classify_intent_llm()      — intent + entity extraction in one call
  2. extract_info_llm()         — Channel A: hard-fact extraction every turn
  3. generate_answer_llm()      — natural-language answer generation
  4. reflect_on_history_llm()   — Channel B: periodic pattern reflection (background)

Channel A vs Channel B
    A (extract_info_llm): runs every turn, captures things the user EXPLICITLY
      said — course enrollment, identity, target GPA, etc. Goes straight into
      session state and long-term memory.
    B (reflect_on_history_llm): runs every N turns in a background task,
      reviews the recent conversation, infers SOFT patterns / preferences
      (which the user did not explicitly state) and persists them.

Configuration via env vars:
    DEEPSEEK_API_KEY   — required to enable LLM (otherwise rule-based fallback)
    DEEPSEEK_MODEL     — default 'deepseek-v4-flash'
    DEEPSEEK_BASE_URL  — default 'https://api.deepseek.com'
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
LLM_ENABLED = bool(DEEPSEEK_API_KEY)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
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
- "off_topic": question is unrelated to courses

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
EXPLICITLY stated or clearly implied by the user.

Return ONLY a JSON object with these fields (use null or [] if not mentioned):
{
  "term": "Fall 2025" | "Winter 2026" | etc. | null,
  "major": "Computer Science" | "Informatics" | "Data Science" | etc. | null,
  "year": "freshman" | "sophomore" | "junior" | "senior" | "1st year" | "2nd year" | "3rd year" | "4th year" | null,
  "target_gpa": number (e.g. 3.7) | null,
  "graduation_term": "Spring 2027" | etc. | null,
  "difficulty_preference": "easy" | "hard" | null,
  "recommendation_goal": "major_requirement" | "easy_gpa" | "professor_quality" | "ge_fulfillment" | null,
  "currently_taking": ["STATS67", ...] | [],
  "completed": ["ICS32", ...] | [],
  "course_ids": ["ICS33", ...] | [],
  "professor_names": ["Thornton", ...] | []
}

IMPORTANT — distinguish course mention status:
- "currently_taking": "I'm taking X", "I'm in X", "currently enrolled in X", "正在上 X"
- "completed": "I took X", "I've finished X", "I passed X", "已修过 X"
- "course_ids": every other course mention with no clear status

Course codes are case-insensitive, return UPPERCASE in canonical UCI form.
The same course must NEVER appear in both currently_taking and completed.
DO NOT GUESS — only extract what's explicit.
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
- Pay attention to constraints the student mentions ("X is full", "I can't take Y", \
"avoid morning") — never recommend a course the student has explicitly excluded
- For single-point queries (one course or one professor), answer concisely
- Use **bold** for course IDs and key headers
- Keep your response focused — aim for clarity over length
"""

REFLECTION_SYSTEM_PROMPT = """\
You observe a UCI course advisor's conversation with a student. Your sole job
is to spot NEW long-term SOFT preferences or patterns that should be remembered
across future sessions.

Look for IMPLICIT signals:
- Repeated topics or kinds of courses the student keeps asking about
- Implicit values (asks RMP scores often → cares about prof quality)
- Scheduling preferences hinted at across multiple turns ("morning bad" twice)
- Decision-making style ("always asks workload before deciding")
- What the student avoids or pushes back on

DO NOT capture:
- Hard facts already extracted on every turn (major, year, currently_taking, \
completed, target_gpa, graduation_term, difficulty_preference, recommendation_goal)
- Things the student stated only ONCE without it being a pattern
- Anything already in the existing-preferences list

Return ONLY a JSON object in this exact shape:
{"preferences": ["short pref under 80 chars", "...", ...]}

If nothing genuinely NEW and pattern-worthy emerges: {"preferences": []}
Maximum 3 preferences per call. Each must be a single short sentence.
"""


# ── Core LLM call ────────────────────────────────────────

async def _call_llm(
    system: str,
    user_content: str,
    json_mode: bool = False,
) -> str:
    """Single LLM call via DeepSeek's OpenAI-compatible Chat Completions API."""
    client = _get_client()
    kwargs = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    content = choice.message.content or ""

    if choice.finish_reason == "length":
        logger.warning("LLM hit server-default output limit.")
    elif not content:
        logger.warning(
            "LLM returned empty content (finish_reason=%s, model=%s).",
            choice.finish_reason, LLM_MODEL,
        )
    return content


def _parse_json_response(text: str) -> Optional[dict]:
    cleaned = text.strip()
    if not cleaned:
        return None
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
    if not LLM_ENABLED:
        return None
    try:
        raw = await _call_llm(INTENT_SYSTEM_PROMPT, user_message, json_mode=True)
        result = _parse_json_response(raw)
        if result and "intent" in result:
            return result
        return None
    except Exception as e:
        logger.error("classify_intent_llm failed: %s", e)
        return None


async def extract_info_llm(user_message: str) -> Optional[dict]:
    """Channel A: extract hard facts the user explicitly stated this turn."""
    if not LLM_ENABLED:
        return None
    try:
        raw = await _call_llm(EXTRACTION_SYSTEM_PROMPT, user_message, json_mode=True)
        return _parse_json_response(raw)
    except Exception as e:
        logger.error("extract_info_llm failed: %s", e)
        return None


async def generate_answer_llm(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
    memory_context: Optional[dict] = None,
) -> Optional[str]:
    if not LLM_ENABLED:
        return None
    try:
        system = _build_system_prompt(memory_context)
        context = _build_answer_context(user_message, retrieved_data, session_state, memory_context)
        raw = await _call_llm(system, context)
        cleaned = raw.strip() if raw else ""
        if not cleaned:
            logger.warning("generate_answer_llm got empty content; falling back.")
            return None
        return cleaned
    except Exception as e:
        logger.error("generate_answer_llm failed: %s", e)
        return None


async def reflect_on_history_llm(
    history: list[dict],
    existing_preferences: list[str],
) -> list[str]:
    """
    Channel B: review recent turns and extract NEW soft preferences.

    Runs as a background task — independent of the user-facing answer call.
    Returns a list of short preference strings (already deduped against
    `existing_preferences` by the LLM).
    """
    if not LLM_ENABLED or not history:
        return []
    try:
        # Format last ~10 messages as a transcript
        recent = history[-10:]
        transcript_lines = []
        for m in recent:
            role = m.get("role", "?")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            transcript_lines.append(f"{role.upper()}: {content[:500]}")
        transcript = "\n".join(transcript_lines)

        existing_block = (
            "\n".join(f"- {p}" for p in existing_preferences[-15:])
            or "(no existing preferences yet)"
        )

        user_content = (
            f"EXISTING PREFERENCES (do not repeat any of these):\n{existing_block}\n\n"
            f"RECENT CONVERSATION:\n{transcript}"
        )
        raw = await _call_llm(REFLECTION_SYSTEM_PROMPT, user_content, json_mode=True)
        result = _parse_json_response(raw)
        if isinstance(result, dict):
            prefs = result.get("preferences", [])
            return [str(p).strip() for p in prefs if p and str(p).strip()]
        return []
    except Exception as e:
        logger.error("reflect_on_history_llm failed: %s", e)
        return []


# ── Internal helpers ─────────────────────────────────────

def _build_system_prompt(memory_context: Optional[dict]) -> str:
    """Compose ANSWER_SYSTEM_PROMPT + persistent profile (no inline nudge anymore)."""
    if not memory_context:
        return ANSWER_SYSTEM_PROMPT
    parts = [ANSWER_SYSTEM_PROMPT]
    block = memory_context.get("system_prompt_block")
    if block:
        parts.append("\n\n--- Persistent context about this student ---\n" + block)
    return "".join(parts)


def _build_answer_context(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
    memory_context: Optional[dict] = None,
) -> str:
    parts = []
    parts.append(f"STUDENT MESSAGE: {user_message}")
    parts.append("")

    if memory_context:
        prefetched = memory_context.get("prefetched_context")
        if prefetched:
            parts.append(prefetched)
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
