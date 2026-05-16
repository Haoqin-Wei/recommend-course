"""
LLM Adapter — DeepSeek via OpenAI-compatible SDK

Public functions:
  1. classify_intent_llm()
  2. extract_info_llm()         — Channel A
  3. generate_answer_llm()
  4. reflect_on_history_llm()   — Channel B
"""

import os
import json
import logging
import asyncio
from typing import Optional, AsyncIterator

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
LLM_ENABLED = bool(DEEPSEEK_API_KEY)

_client = None


def _get_client():
    """Return a process-wide AsyncOpenAI client. Created lazily."""
    global _client
    if _client is None:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
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
  "year": "freshman" | "sophomore" | "junior" | "senior" | null,
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
- If a candidate has `conflict_status: "all"`, you MUST warn the student that \
it conflicts with their current schedule and reference the conflicting course \
shown in `conflict_summary`. Suggest dropping the conflict, or pivoting to a \
non-conflicting alternative.
- If a candidate has `conflict_status: "some"`, note that not every section \
fits the schedule and suggest which sections to look at (the ones with empty \
`conflicts_with` arrays).
- For single-point queries (one course or one professor), answer concisely
- Use **bold** for course IDs and key headers
- Keep your response focused — aim for clarity over length
- Do NOT output a "Data check", "Validation", "数据校验", or similar \
section yourself. The system appends a separate validation footer below \
your answer; emitting one yourself creates a confusing duplicate.
"""

REFLECTION_SYSTEM_PROMPT = """\
You observe a UCI course advisor's conversation with a student. Your job is to
extract any soft preferences worth remembering across future sessions.

Capture things like:
- Stated likes/dislikes about course style ("I like easy courses", "I prefer \
project-based classes")
- Scheduling habits ("I avoid mornings", "Friday off")
- Decision-making patterns ("Always asks workload before committing", "Cares \
a lot about RMP scores")
- Topic interests ("Keeps asking about ML / databases / AI")
- Anything else that would help a future session personalize advice

Even single-mention preferences are worth recording — better to capture and let
deduplication handle it later than to miss it. Just stay short and concrete.

DO NOT capture:
- Hard facts already extracted on every turn (major, year, currently_taking, \
completed, target_gpa, graduation_term — these have their own pipeline)
- Anything already in the existing-preferences list (don't restate)

Return ONLY a JSON object in this exact shape:
{"preferences": ["short pref under 80 chars", "...", ...]}

If genuinely nothing new: {"preferences": []}
Maximum 3 preferences per call. Each preference must be one short sentence.
"""


# ── Core LLM call ────────────────────────────────────────

async def _call_llm(
    system: str,
    user_content: str,
    json_mode: bool = False,
) -> str:
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

    response = await client.chat.completions.create(**kwargs)
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
        result = _parse_json_response(raw)
        # Log non-empty fields so the operator can see what the LLM picked up.
        if result:
            non_empty = {k: v for k, v in result.items() if v not in (None, "", [])}
            if non_empty:
                logger.info("[Channel A] LLM extracted: %s", non_empty)
            else:
                logger.info("[Channel A] LLM returned all-empty extraction")
        else:
            logger.info("[Channel A] LLM extraction returned None")
        return result
    except Exception as e:
        logger.error("extract_info_llm failed: %s", e)
        return None


async def generate_answer_llm(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
    memory_context: Optional[dict] = None,
    system_prompt_override: Optional[str] = None,
    # ── Phase 3.4: structured context layers (all optional for back-compat) ──
    recent_turns: Optional[list[dict]] = None,
    decisions: Optional[list[dict]] = None,
    summary: Optional[str] = None,
    profile: Optional[dict] = None,
    preferences: Optional[list] = None,
    facts: Optional[list] = None,
) -> Optional[str]:
    if not LLM_ENABLED:
        return None
    try:
        messages = _build_messages_for_llm(
            user_message=user_message,
            retrieved_data=retrieved_data,
            session_state=session_state,
            memory_context=memory_context,
            system_prompt_override=system_prompt_override,
            recent_turns=recent_turns,
            decisions=decisions,
            summary=summary,
            profile=profile,
            preferences=preferences,
            facts=facts,
        )
        raw = await _call_llm_with_messages(messages)
        cleaned = raw.strip() if raw else ""
        if not cleaned:
            logger.warning("generate_answer_llm got empty content; falling back.")
            return None
        return cleaned
    except Exception as e:
        logger.error("generate_answer_llm failed: %s", e)
        return None


async def stream_answer_llm(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
    memory_context: Optional[dict] = None,
    system_prompt_override: Optional[str] = None,
    # ── Phase 3.4: structured context layers (all optional for back-compat) ──
    recent_turns: Optional[list[dict]] = None,
    decisions: Optional[list[dict]] = None,
    summary: Optional[str] = None,
    profile: Optional[dict] = None,
    preferences: Optional[list] = None,
    facts: Optional[list] = None,
) -> AsyncIterator[str]:
    """
    Streaming variant of generate_answer_llm.

    Yields delta strings as they arrive from the model. Caller can
    accumulate them to reconstruct the full answer.

    Cancellation:
        If the consumer (FastAPI streaming response) is cancelled
        because the HTTP client disconnected, asyncio.CancelledError
        propagates up here. We let it bubble out — the AsyncOpenAI
        client will then close its underlying connection to DeepSeek,
        which stops further token generation server-side. This is the
        whole point: a real Stop button that doesn't waste API tokens.
    """
    if not LLM_ENABLED:
        return

    messages = _build_messages_for_llm(
        user_message=user_message,
        retrieved_data=retrieved_data,
        session_state=session_state,
        memory_context=memory_context,
        system_prompt_override=system_prompt_override,
        recent_turns=recent_turns,
        decisions=decisions,
        summary=summary,
        profile=profile,
        preferences=preferences,
        facts=facts,
    )

    client = _get_client()
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            stream=True,
        )
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except asyncio.CancelledError:
        logger.info("stream_answer_llm cancelled (client disconnected) — "
                    "closing upstream connection")
        raise
    except Exception as e:
        logger.error("stream_answer_llm failed: %s", e)
        return


async def reflect_on_history_llm(
    history: list[dict],
    existing_preferences: list[str],
) -> list[str]:
    """Channel B: extract NEW soft preferences from recent turns."""
    if not LLM_ENABLED:
        logger.info("[Channel B] skipped: LLM disabled")
        return []
    if not history:
        logger.info("[Channel B] skipped: empty history")
        return []
    try:
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
        logger.info(
            "[Channel B] running reflection (%d messages, %d existing preferences)",
            len(transcript_lines), len(existing_preferences),
        )
        raw = await _call_llm(REFLECTION_SYSTEM_PROMPT, user_content, json_mode=True)
        result = _parse_json_response(raw)
        if isinstance(result, dict):
            prefs = result.get("preferences", [])
            cleaned = [str(p).strip() for p in prefs if p and str(p).strip()]
            return cleaned
        return []
    except Exception as e:
        logger.error("reflect_on_history_llm failed: %s", e)
        return []


# ── Internal helpers ─────────────────────────────────────

def get_default_answer_prompt() -> str:
    """
    Public accessor used by /api/system_prompt to seed the frontend's
    Settings modal with the current default. If the prompt is ever
    refactored (split, templatized, etc.), update this one function
    instead of teaching the endpoint about a new name.
    """
    return ANSWER_SYSTEM_PROMPT


def _build_system_prompt(
    memory_context: Optional[dict],
    override: Optional[str] = None,
) -> str:
    """
    Compose the final system message sent to the LLM.

    Layering:
      base  ← `override` if a non-empty custom prompt was supplied,
              otherwise the default ANSWER_SYSTEM_PROMPT
      +memory block (per-student persistence) is still appended in either case,
              so customizing the advisor's voice doesn't drop the user's profile.

    Pass `override=""` or `None` to use the default.
    """
    base = override.strip() if (override and override.strip()) else ANSWER_SYSTEM_PROMPT
    if override and override.strip():
        logger.info("generate_answer_llm: using user-supplied system prompt override (%d chars)",
                    len(override.strip()))

    if not memory_context:
        return base
    block = memory_context.get("system_prompt_block")
    if not block:
        return base
    return base + "\n\n--- Persistent context about this student ---\n" + block


def _build_answer_context(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
    memory_context: Optional[dict] = None,
) -> str:
    """
    LEGACY: monolithic single-string context. Kept for backwards compat
    with any caller that still uses generate_answer_llm or
    stream_answer_llm without the new structured params. The new code
    path goes through _build_messages_for_llm below.
    """
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


# ══════════════════════════════════════════════════════════
#  Phase 3.4: structured 6-layer context (new code path)
# ══════════════════════════════════════════════════════════

def _build_messages_for_llm(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
    memory_context: Optional[dict] = None,
    system_prompt_override: Optional[str] = None,
    recent_turns: Optional[list[dict]] = None,
    decisions: Optional[list[dict]] = None,
    summary: Optional[str] = None,
    profile: Optional[dict] = None,
    preferences: Optional[list] = None,
    facts: Optional[list] = None,
) -> list[dict]:
    """
    Build the OpenAI-style messages list using the 6-layer context.

    If `recent_turns` is provided, this uses the new layered builder
    (context_builder.build_messages). If absent, falls back to the
    legacy single-string context so that older callers keep working
    until chat.py is fully updated.
    """
    # Static system prompt (with optional override)
    base_system = (
        system_prompt_override.strip()
        if (system_prompt_override and system_prompt_override.strip())
        else ANSWER_SYSTEM_PROMPT
    )

    # If no structured context was passed, use the legacy single-string format
    # so that this function is a drop-in replacement for the old flow.
    if recent_turns is None and decisions is None and summary is None \
            and profile is None and preferences is None and facts is None:
        system = _build_system_prompt(memory_context, system_prompt_override)
        context = _build_answer_context(
            user_message, retrieved_data, session_state, memory_context,
        )
        return [
            {"role": "system", "content": system},
            {"role": "user",   "content": context},
        ]

    # New path: structured 6-layer assembly
    from app.llm import context_builder

    # If profile/preferences weren't passed but memory_context has the
    # rendered block, fold it into the system message as before so we
    # don't lose information.
    fallback_memory_block = None
    if memory_context and not (profile or preferences or facts):
        fallback_memory_block = memory_context.get("system_prompt_block")

    # We use session_state to derive a minimal profile if none provided —
    # keeps the call site simple while still showing the LLM the basics.
    derived_profile = profile or {
        "major":             session_state.get("major"),
        "year":              session_state.get("year"),
        "completed_courses": session_state.get("completed_courses") or [],
        "selected_courses":  session_state.get("selected_courses") or [],
    }

    base_with_legacy = base_system
    if fallback_memory_block:
        base_with_legacy = (
            base_system
            + "\n\n--- Persistent context about this student ---\n"
            + fallback_memory_block
        )

    return context_builder.build_messages(
        system_prompt=base_with_legacy,
        user_message=user_message,
        profile=derived_profile,
        preferences=preferences,
        facts=facts,
        decisions=decisions,
        summary=summary,
        recent_turns=recent_turns,
        retrieved_data=retrieved_data,
        last_n_turns=10,
    )


async def _call_llm_with_messages(messages: list[dict]) -> Optional[str]:
    """
    Non-streaming LLM call given a pre-built messages list.
    Used by generate_answer_llm.
    """
    client = _get_client()
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
        )
        if not response.choices:
            return None
        return response.choices[0].message.content
    except Exception as e:
        logger.error("_call_llm_with_messages failed: %s", e)
        return None
