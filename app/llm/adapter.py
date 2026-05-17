"""
LLM Adapter — DeepSeek via OpenAI-compatible SDK

Public functions:
  1. classify_intent_llm()         — with deterministic rule pre-classifier
  2. extract_info_llm()            — Channel A
  3. generate_answer_llm()
  4. stream_answer_llm()
  5. reflect_on_history_llm()      — Channel B
  6. generate_session_title_llm()  — Round 4: auto-title for new sessions
"""

import os
import json
import logging
import asyncio
from typing import Optional, AsyncIterator

# ── Load .env BEFORE reading any env var ─────────────────
# Rationale: uvicorn doesn't auto-load .env. If the user starts the
# server in a fresh shell without `set -a; source .env; set +a`, the
# DEEPSEEK_API_KEY won't be visible to os.environ — adapter would
# silently set LLM_ENABLED=False and every LLM call would no-op,
# falling back to static templates. Loading dotenv here makes the
# adapter self-sufficient.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed — assume env is set externally.
    pass

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
- "course_recommendation": user wants course suggestions, comparisons across \
multiple courses, schedule planning, or personalized advice ("what should I take?")
- "single_query": user asks about ONE specific course or ONE specific professor, \
OR makes a commitment/decision about ONE specific course ("I'll take CS122A", \
"我决定选 CS122A", "drop CS131"). Decisions go here because the user wants \
focused analysis of THAT course, not fresh suggestions.
- "off_topic": question is completely unrelated to courses, professors, or \
academic planning (weather, sports, general life advice, etc.)

DEFAULT BIAS: if the message mentions ANY course code (CS122A, ICS33, etc.), \
or any course-related verb (选/修/上 / take/enroll/drop), it is NEVER off_topic. \
Pick course_recommendation or single_query.

Examples — study these to handle similar inputs:

User: "我决定选 CS122A"
→ {"intent": "single_query", "confidence": 0.95, "entities": {"course_ids": ["CS122A"], "professor_names": [], "term": null, "major": null, "difficulty_preference": null, "recommendation_goal": null}}

User: "I'll take CS161 next quarter"
→ {"intent": "single_query", "confidence": 0.95, "entities": {"course_ids": ["CS161"], "professor_names": [], "term": null, "major": null, "difficulty_preference": null, "recommendation_goal": null}}

User: "CS131 怎么样？"
→ {"intent": "single_query", "confidence": 0.95, "entities": {"course_ids": ["CS131"], "professor_names": [], "term": null, "major": null, "difficulty_preference": null, "recommendation_goal": null}}

User: "Tell me about MATH2A"
→ {"intent": "single_query", "confidence": 0.95, "entities": {"course_ids": ["MATH2A"], "professor_names": [], "term": null, "major": null, "difficulty_preference": null, "recommendation_goal": null}}

User: "How is professor Thornton?"
→ {"intent": "single_query", "confidence": 0.95, "entities": {"course_ids": [], "professor_names": ["Thornton"], "term": null, "major": null, "difficulty_preference": null, "recommendation_goal": null}}

User: "推荐几门 CS 课"
→ {"intent": "course_recommendation", "confidence": 0.95, "entities": {"course_ids": [], "professor_names": [], "term": null, "major": "Computer Science", "difficulty_preference": null, "recommendation_goal": null}}

User: "What's a good easy GE I could take?"
→ {"intent": "course_recommendation", "confidence": 0.95, "entities": {"course_ids": [], "professor_names": [], "term": null, "major": null, "difficulty_preference": "easy", "recommendation_goal": "ge_fulfillment"}}

User: "compare CS122A and CS131"
→ {"intent": "course_recommendation", "confidence": 0.9, "entities": {"course_ids": ["CS122A", "CS131"], "professor_names": [], "term": null, "major": null, "difficulty_preference": null, "recommendation_goal": null}}

User: "你能帮我看看下学期排课吗"
→ {"intent": "course_recommendation", "confidence": 0.9, "entities": {"course_ids": [], "professor_names": [], "term": null, "major": null, "difficulty_preference": null, "recommendation_goal": null}}

User: "今天天气怎么样？"
→ {"intent": "off_topic", "confidence": 0.95, "entities": {"course_ids": [], "professor_names": [], "term": null, "major": null, "difficulty_preference": null, "recommendation_goal": null}}

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

# ── Agent loop system prompt ─────────────────────────────
AGENT_SYSTEM_PROMPT = """\
You are a UCI course advisor chatbot. You speak naturally, like a \
knowledgeable upperclassman who genuinely wants to help — not like a \
database printout.

# Tools

You have tools to look up real UCI data. Use them aggressively rather than \
guessing. The student's basics (major, year, completed courses, currently \
enrolled, term) are in the system context below; for anything more specific \
— catalog info, sections, grades, professor ratings, prerequisites, schedule \
conflicts, the student's preferences — call the relevant tool.

Examples of when to call tools:
- "CS122A 跟 ICS46 冲突吗" → check_section_conflict(course_a="CS122A", course_b="ICS46")
- "Thornton 评价怎么样"     → get_professor_rating(instructor_name="Thornton, A.")
- "CS122A 难吗"             → get_grade_distribution(course_id="CS122A")
- "我能上 CS161 吗"          → check_prerequisites_met(course_id="CS161")  (uses profile)
- "推荐几门简单的 GE"        → search_courses(ge_category="...") then optionally
                              get_grade_distribution on each candidate

Rules of thumb:
- It's fine to chain tools. It's fine to call multiple tools in one turn.
- Don't call a tool when the answer is already in the student profile / context.
- Don't call get_course_info just to confirm a course exists — use a more \
specific tool (get_sections, get_grade_distribution) and rely on its \
`found=false` / `error` field.
- If a tool returns `error` or `found=false`, acknowledge it honestly rather \
than inventing data.

# Answer format

After you have enough data, reply in this structure:
1. **Conclusion first** — state your direct answer / top 1–3 recommendations
2. **Reasons** — 1–3 sentences per pick, grounded in the tool results
3. **Risk warnings** — unmet prereqs, time conflicts, heavy workload
4. **Alternatives** — if your top pick has issues, suggest a safer backup
5. **Follow-up questions** — end with 2–3 natural next-step suggestions

# Style

- Match the student's language (Chinese in → Chinese out, English in → English out)
- Be direct, practical, conversational
- Convert raw data into judgments ("historically generous grading" not "avg GPA 3.4")
- Use **bold** for course IDs and key headers
- Do NOT output a "Data check" / "Validation" / "数据校验" section — the \
system appends a separate validation footer below your answer.
"""


# ── Round 4: session auto-title prompt ───────────────────
TITLE_SYSTEM_PROMPT = """\
You generate a short title for a UCI course advisor conversation.

CONSTRAINTS:
- Output ONLY the title text. No quotes. No "Title:" prefix. No trailing period.
- Aim for 5–10 characters. Chinese characters count as 1 each.
- Match the user's language:
    Chinese user input → Chinese title (English course codes like "CS122A" are fine)
    English user input → English title
- Capture the SPECIFIC topic (course ID, question type), not generic terms.

EXAMPLES:

User: "我决定选CS122A"
Reply: "好的，CS122A 是软件设计课..."
Title: 选CS122A

User: "推荐几门简单的GE"
Reply: "几门工作量较轻的 GE 课程..."
Title: 简单GE推荐

User: "How is Thornton?"
Reply: "Thornton is highly rated for..."
Title: Thornton review

User: "compare CS122A and CS131"
Reply: "Both are upper-division CS..."
Title: CS122A vs CS131

User: "下学期能不能不上早八"
Reply: "可以的，避开早 8 点的课..."
Title: 避开早八排课

BAD examples (do not produce these):
- "Conversation about courses" (too generic)
- "标题：选CS122A" (prefix forbidden)
- "「选 CS122A」" (quotes forbidden)
- "User wants to take CS122A." (too long, ends with period)
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
    """
    Two-stage intent classifier (Phase 3 polish — stability fix).

    Stage 1: deterministic regex rules cover high-confidence patterns
    ("我决定选 X", "I'll take Y", "compare X and Y", "推荐课"). When a
    rule matches, return immediately — zero LLM cost, fully reproducible.

    Stage 2: ambiguous inputs fall through to the LLM classifier with
    few-shot examples baked into the system prompt. The LLM is still
    non-deterministic but examples reduce the variance significantly,
    and crucially, the rules above mean the most common course-related
    inputs never hit this stage in the first place.
    """
    # Stage 1: rules
    try:
        from app.llm import intent_rules
        rule_result = intent_rules.classify_by_rules(user_message)
        if rule_result:
            logger.info(
                "[intent] rule-match (%s) → %s",
                rule_result.get("rule_id"),
                rule_result.get("intent"),
            )
            return rule_result
    except Exception as e:
        # Don't let a regex bug kill the request — log and fall through.
        logger.warning("intent_rules failed: %s", e)

    # Stage 2: LLM fallback
    if not LLM_ENABLED:
        return None
    try:
        raw = await _call_llm(INTENT_SYSTEM_PROMPT, user_message, json_mode=True)
        result = _parse_json_response(raw)
        if result and "intent" in result:
            result["source"] = "llm"
            logger.info("[intent] LLM → %s", result.get("intent"))
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


# ── Agent-loop streaming entry point ─────────────────────

async def stream_agent_response(
    user_message: str,
    session_state: dict,
    *,
    user_id: str,
    memory_context: Optional[dict] = None,
    system_prompt_override: Optional[str] = None,
    recent_turns: Optional[list[dict]] = None,
    decisions: Optional[list[dict]] = None,
    summary: Optional[str] = None,
    profile: Optional[dict] = None,
    preferences: Optional[list] = None,
    facts: Optional[list] = None,
):
    """
    Agent-loop variant of stream_answer_llm. Builds the 6-layer
    context with AGENT_SYSTEM_PROMPT as the base prompt (no
    retrieved_data block — the agent fetches data itself via tools)
    and hands it to app.agent.loop.run_agent.

    Yields the agent loop's event protocol verbatim:
        {"type": "token", "text": ...}            — answer text deltas
        {"type": "tool_call_start", ...}          — before each tool dispatch
        {"type": "tool_call_done",  ...}          — after each tool dispatch
        {"type": "final", "text": ..., ...}       — terminal success
        {"type": "error", "message": ...}         — bound hit or LLM failure

    Falls back to silent return if LLM_ENABLED is false — chat.py will
    then drop into the legacy handler path.
    """
    if not LLM_ENABLED:
        return

    from app.llm import context_builder
    from app.agent.loop import run_agent

    base_system = (
        system_prompt_override.strip()
        if (system_prompt_override and system_prompt_override.strip())
        else AGENT_SYSTEM_PROMPT
    )
    # Memory block injection mirrors stream_answer_llm so the agent
    # has the same persistent-context awareness as the legacy path.
    fallback_memory_block = None
    if memory_context and not (profile or preferences or facts):
        fallback_memory_block = memory_context.get("system_prompt_block")
    if fallback_memory_block:
        base_system = (
            base_system
            + "\n\n--- Persistent context about this student ---\n"
            + fallback_memory_block
        )

    derived_profile = profile or {
        "major":             session_state.get("major"),
        "year":              session_state.get("year"),
        "completed_courses": session_state.get("completed_courses") or [],
        "selected_courses":  session_state.get("selected_courses") or [],
    }

    messages = context_builder.build_messages(
        system_prompt=base_system,
        user_message=user_message,
        profile=derived_profile,
        preferences=preferences,
        facts=facts,
        decisions=decisions,
        summary=summary,
        recent_turns=recent_turns,
        retrieved_data=None,    # agent fetches via tools, not prefetch
        last_n_turns=10,
    )

    client = _get_client()
    try:
        async for event in run_agent(
            messages, client=client, model=LLM_MODEL, user_id=user_id,
        ):
            yield event
    except asyncio.CancelledError:
        logger.info("stream_agent_response cancelled (client disconnected)")
        raise
    except Exception as e:
        logger.error("stream_agent_response failed: %s: %s", type(e).__name__, e)
        yield {"type": "error", "message": str(e)}


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


# ── Round 4: session auto-title ──────────────────────────

async def generate_session_title_llm(
    user_message: str,
    assistant_reply: str,
) -> Optional[str]:
    """
    Round 4 — generate a short (5–10 char) title from the first turn.

    chat.py fires this from a FastAPI BackgroundTask after the first
    user→assistant exchange in a brand-new session is persisted. It
    replaces the snippet placeholder title (first 30 chars of the user
    message) with something compact and topical, e.g.
        "我决定选CS122A怎么样" → "选CS122A"
        "推荐几门简单的GE"     → "简单GE推荐"

    Fire-and-forget: failures return None so the caller can keep the
    snippet title. No retry, no fallback model.

    The assistant reply is truncated to 500 chars before being shown
    to the model — title generation only needs the gist of the topic,
    not the entire grounded answer.
    """
    if not LLM_ENABLED:
        return None

    trimmed_reply = (assistant_reply or "")[:500]
    user_content = (
        f"USER MESSAGE:\n{user_message}\n\n"
        f"ADVISOR REPLY (truncated):\n{trimmed_reply}"
    )

    try:
        raw = await _call_llm(TITLE_SYSTEM_PROMPT, user_content)
    except Exception as e:
        logger.error("generate_session_title_llm failed: %s", e)
        return None

    if not raw:
        return None

    # ── Post-processing: strip common LLM verbosity ──
    title = raw.strip()

    # Take first line only (LLM occasionally adds a second line of
    # commentary — "Title: X\n(short and specific)")
    title = title.split("\n", 1)[0].strip()

    # Strip common prefixes
    for prefix in ("Title:", "title:", "TITLE:", "标题:", "标题：", "Title："):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
            break

    # Strip surrounding quote pairs (ASCII + CJK + smart quotes + backticks)
    quote_pairs = (
        ('"', '"'), ("'", "'"),
        ("\u201C", "\u201D"),   # smart double "
        ("\u2018", "\u2019"),   # smart single '
        ("\u300C", "\u300D"),   # 「 」
        ("\u300E", "\u300F"),   # 『 』
        ("\u300A", "\u300B"),   # 《 》
        ("`", "`"),
    )
    for open_q, close_q in quote_pairs:
        if len(title) >= 2 and title.startswith(open_q) and title.endswith(close_q):
            title = title[len(open_q):-len(close_q)].strip()
            break

    # Strip trailing punctuation
    title = title.rstrip("。.!?！？,;；:：")

    # Safety: hard cap at 30 chars in case the model ignored the length rule
    if len(title) > 30:
        title = title[:30].rstrip()

    if not title:
        return None

    return title


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
