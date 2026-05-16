"""
Chat Router — orchestrates the SKILL.md pipeline.

Two-channel memory architecture:
    Channel A (immediate, every turn):
        extract_info_llm() pulls hard facts from the user's message.
        _capture_hard_facts() routes them to the right destinations:
          • course status → session lists + facts.json
          • identity → profile.json
          • stated preferences (difficulty / goal) → facts.json

    Channel B (periodic, background):
        Every REFLECTION_INTERVAL turns, after the response is sent,
        FastAPI BackgroundTasks fires _run_reflection_task(). That task
        spawns an independent LLM call for SOFT pattern detection.

Validation (Phase 1):
    After generate_answer_llm() returns, the answer is run through the
    Phase 1 validator suite (course_exists / instructor / offered_term /
    consistency). Hallucinated course IDs and unknown professors get
    annotated as footer issues. validation_report is attached to
    ChatResponse for inspection.

Logging:
    INFO-level logs at every capture and reflection step so the operator
    can watch the memory pipeline live in the uvicorn terminal.
"""

import logging
import re

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from app.modules.intent import classify_intent
from app.modules.state import (
    get_or_create_session, update_session, add_message,
    load_student_into_session, get_known_fields,
)
from app.modules.clarification import (
    detect_missing_fields, needs_clarification,
    build_clarification_response, extract_info_from_message,
)
from app.modules.query import (
    query_course_recommendations, query_single_course, query_professor,
)
from app.modules.answer import (
    generate_recommendation_answer, generate_single_query_answer,
    generate_professor_answer, generate_off_topic_response,
)
from app.modules.followup import generate_followups, generate_single_query_followups
from app.memory import get_memory_manager

# ── Phase 3.3 / 3.5 — session storage + decision detection ──
from app.data import sessions as sessions_data
from app.modules import decision_detector
from app.modules import state as state_module
# ─────────────────────────────────────────────────────────────

# ── Validation Phase 1 ───────────────────────────────────
from app.catalog.term import Term, get_term_registry
from app.catalog.cache import get_catalog
from app.validation import (
    ValidationContext, validate, decide_action, apply_report, write_log,
)
# ─────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter()

# Scan for course IDs anywhere in a string.
#
# We use explicit ASCII look-arounds instead of \b because Python's
# regex \b is Unicode-aware by default: in "我决定选CS122A", the
# character 选 is classified as a "word" character (it's alphanumeric
# in Unicode), so \b between 选 and CS does NOT match. The same
# problem hits course IDs sandwiched between Chinese characters
# anywhere ("选CS122A课"). The look-arounds below say "not preceded /
# followed by an ASCII letter or digit" — Chinese characters are
# fine as neighbors.
_COURSE_ID_SCAN = re.compile(
    r'(?<![A-Za-z0-9])[A-Z]{1,8}\d+[A-Z]?(?![A-Za-z0-9])',
    re.IGNORECASE,
)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "demo_session"
    student_id: Optional[str] = "demo_001"
    term: Optional[str] = None                          # 新增
    system_prompt: Optional[str] = None                 # 新增：前端自定义 LLM system prompt


class ChatResponse(BaseModel):
    reply: str
    cards: list[dict] = []
    followups: list[str] = []
    intent: str = ""
    session_state: dict = {}
    pending_schedule: list[dict] = []
    validation_report: Optional[dict] = None            # 新增


# ── Phase 3.3 — session_id resolution ────────────────────
#
# The frontend still sends "demo_session" (legacy hardcoded) until
# Round 3 lands. We translate that into a real persistent session_id
# (sess_XXXXXX) by either reusing the in-memory mapping or auto-creating
# one. The persistent_session_id is cached on the in-memory session
# dict so subsequent requests in the same server lifetime reuse it.
#
# After Round 3, the frontend sends real session_ids directly and this
# resolution becomes a no-op (the real id is used as-is).

def _resolve_session_id(
    req_session_id: str,
    user_id: str,
    term_str: Optional[str] = None,
) -> str:
    """
    Translate the request's session_id into a persistent session_id
    on disk. Returns a session_id starting with 'sess_'.
    """
    # Case 1: frontend already sent a real session_id and it exists
    if req_session_id and req_session_id.startswith("sess_"):
        try:
            sessions_data.get_session_meta(user_id, req_session_id)
            return req_session_id
        except (sessions_data.SessionNotFound, sessions_data.InvalidId):
            logger.warning(
                "[stream] requested session_id %r not found; falling back to auto-create",
                req_session_id,
            )

    # Case 2: legacy request — check in-memory mapping first
    in_mem = state_module._sessions.get(req_session_id, {})
    cached = in_mem.get("persistent_session_id")
    if cached:
        try:
            sessions_data.get_session_meta(user_id, cached)
            return cached
        except sessions_data.SessionNotFound:
            # Session was deleted externally — fall through to recreate
            pass

    # Case 3: no usable session — create a new one and cache the mapping
    new_sid = sessions_data.create_session(
        user_id,
        title="New conversation",
        term_scope=term_str,
    )
    if req_session_id not in state_module._sessions:
        state_module._sessions[req_session_id] = state_module._make_empty_session(req_session_id)
    state_module._sessions[req_session_id]["persistent_session_id"] = new_sid
    logger.info(
        "[stream] auto-created persistent session %s (legacy key=%r)",
        new_sid, req_session_id,
    )
    return new_sid


def _hydrate_state_from_session(
    user_id: str,
    persistent_session_id: str,
    in_mem_session: dict,
) -> None:
    """
    On first use of a persistent session in this server lifetime, copy
    its stored turns into in-memory state.history so existing code
    (add_message, etc.) keeps working.

    Idempotent: only hydrates if state.history is empty.
    """
    if in_mem_session.get("history"):
        return
    try:
        turns = sessions_data.read_turns(user_id, persistent_session_id)
    except sessions_data.SessionNotFound:
        return
    in_mem_session["history"] = [
        {"role": t.get("role"), "content": t.get("content")}
        for t in turns
        if t.get("role") in ("user", "assistant")
    ]
    if turns:
        logger.info(
            "[stream] hydrated state.history with %d turns from session %s",
            len(in_mem_session["history"]), persistent_session_id,
        )


def _persist_turn(
    user_id: str,
    persistent_sid: str,
    user_msg: str,
    assistant_reply: str,
) -> int:
    """
    Append user + assistant turns to sessions/{sid}/turns.jsonl.
    Returns the turn_index of the assistant reply (used for decision pinning).
    Failures here are logged but don't break the response.
    """
    try:
        sessions_data.append_turn(user_id, persistent_sid, "user", user_msg)
        idx = sessions_data.append_turn(user_id, persistent_sid, "assistant", assistant_reply)
        return idx
    except Exception as e:
        logger.warning("[stream] persist_turn failed for %s: %s", persistent_sid, e)
        return 0


def _detect_and_pin_decisions(
    user_id: str,
    persistent_sid: str,
    user_msg: str,
    turn_index: int,
) -> None:
    """
    Run the heuristic decision detector on the user's latest message.
    Append any new decisions to session.decisions (idempotent against
    existing on lower-case match). Failures are logged but not fatal.
    """
    try:
        detected = decision_detector.detect_decisions(user_msg)
        for d in detected:
            result = sessions_data.append_decision(
                user_id, persistent_sid, d, from_turn=turn_index,
            )
            if not result.get("already_existed"):
                logger.info("[stream] pinned decision %r in session %s (turn %d)",
                            d, persistent_sid, turn_index)
    except Exception as e:
        logger.warning("[stream] decision-pinning failed: %s", e)


def _resolve_referenced_course(recent_turns: list[dict]) -> Optional[str]:
    """
    Scan recent conversation turns (newest first) for a course ID.

    Used by _handle_single_query when the current user message contains
    no explicit course ID but is likely a follow-up referring to
    something earlier ("那个课", "the first one", "上面提到的那门").

    Prefers user-side mentions (the subject the user steered the
    conversation toward) over assistant-side mentions (the assistant
    might rattle off many courses in a recommendation reply, only one
    of which is what the user wants more info on).

    Returns the most recent course ID seen, or None.
    """
    if not recent_turns:
        return None

    # First pass: walk user turns newest-first
    for turn in reversed(recent_turns):
        if turn.get("role") != "user":
            continue
        matches = _COURSE_ID_SCAN.findall(turn.get("content") or "")
        if matches:
            return matches[0].upper()

    # Second pass: fall back to assistant turns if no user mention
    for turn in reversed(recent_turns):
        if turn.get("role") != "assistant":
            continue
        matches = _COURSE_ID_SCAN.findall(turn.get("content") or "")
        if matches:
            return matches[0].upper()

    return None


# ── Channel A: hard-fact capture (every turn) ────────────

def _merge_into_list(session: dict, field: str, items: list[str]) -> list[str]:
    existing = session.setdefault(field, [])
    existing_upper = {c.upper() for c in existing if c}
    newly_added = []
    for item in items:
        if not item:
            continue
        canonical = item.upper().strip()
        if canonical not in existing_upper:
            existing.append(item)
            existing_upper.add(canonical)
            newly_added.append(item)
    return newly_added


# Identity fields — go to profile.json (long-term identity)
_IDENTITY_FIELDS_FOR_PROFILE = ("major", "year", "target_gpa", "graduation_term")

# Stated-preference fields — go to facts.json as event-style entries
_PREFERENCE_FIELDS_AS_FACTS = {
    "difficulty_preference": "Stated difficulty preference: {value}",
    "recommendation_goal":   "Stated goal: {value}",
}


def _capture_hard_facts(session: dict, extracted: dict, user_id: str, mem) -> None:
    """
    Channel A: pull every explicitly-stated fact out of `extracted`,
    route it to session/profile/facts as appropriate, and emit INFO logs
    so the operator can see what was captured.
    """
    # ── Course status → session lists + facts.json ──
    currently_taking = extracted.pop("currently_taking", None) or []
    completed = extracted.pop("completed", None) or []

    if currently_taking:
        new_courses = _merge_into_list(session, "selected_courses", currently_taking)
        if new_courses and mem.provider:
            for c in new_courses:
                mem.provider.add_fact(user_id, f"Currently taking {c}")
            logger.info("[Channel A] currently_taking captured → %s", new_courses)

    if completed:
        new_courses = _merge_into_list(session, "completed_courses", completed)
        if new_courses and mem.provider:
            for c in new_courses:
                mem.provider.add_fact(user_id, f"Completed {c}")
            logger.info("[Channel A] completed captured → %s", new_courses)

    # ── Identity → profile.json ──
    profile_updates = {}
    for f in _IDENTITY_FIELDS_FOR_PROFILE:
        v = extracted.get(f) if f in ("major", "year") else extracted.pop(f, None)
        if v not in (None, "", []):
            profile_updates[f] = v
    if profile_updates and mem.provider:
        mem.provider.update_profile(user_id, profile_updates)
        logger.info("[Channel A] profile updated → %s", profile_updates)

    # ── Stated preferences → facts.json ──
    for field, template in _PREFERENCE_FIELDS_AS_FACTS.items():
        v = extracted.get(field)
        if v in (None, "", []):
            continue
        if mem.provider:
            mem.provider.add_fact(user_id, template.format(value=v))
            logger.info("[Channel A] preference fact → %s=%s", field, v)


# ── Channel B: background reflection (every N turns) ─────

async def _run_reflection_task(user_id: str, history: list[dict]) -> None:
    """Fired as a FastAPI BackgroundTask AFTER the response is sent."""
    from app.llm.adapter import reflect_on_history_llm
    mem = get_memory_manager()
    if not mem.provider:
        logger.info("[Channel B] skipped: no memory provider")
        return
    existing = mem.get_preferences(user_id)
    new_prefs = await reflect_on_history_llm(history, existing)
    logger.info(
        "[Channel B] reflection ran (history=%d turns, existing prefs=%d) → %d new preferences: %s",
        len(history), len(existing), len(new_prefs), new_prefs,
    )
    for pref in new_prefs:
        mem.add_preference(user_id, pref)


def _course_ids_in_order(text: str) -> list[str]:
    seen, result = set(), []
    for m in _COURSE_ID_SCAN.finditer(text):
        cid = m.group().upper().replace(' ', '')
        if cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


# ── Main chat endpoint ───────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, background_tasks: BackgroundTasks):
    user_id = req.student_id or "anonymous"
    mem = get_memory_manager()

    mem.initialize_session(req.session_id, user_id)

    session = get_or_create_session(req.session_id)
    if not session.get("major") and req.student_id:
        load_student_into_session(req.session_id, req.student_id)
        session = get_or_create_session(req.session_id)

    add_message(req.session_id, "user", req.message)

    mem.on_turn_start(req.session_id, user_id)
    logger.info(
        "[turn %d] user=%s msg=%r",
        mem.turn_count(req.session_id), user_id, req.message[:120],
    )

    # ── Channel A ──
    extracted = await extract_info_from_message(req.message, session)
    if extracted:
        logger.info("[Channel A] extracted from message: %s", extracted)
        _capture_hard_facts(session, extracted, user_id, mem)
        if extracted:
            session = update_session(req.session_id, extracted)
    else:
        logger.info("[Channel A] nothing extracted from message")

    intent_result = await classify_intent(req.message)
    intent = intent_result["intent"]
    logger.info("[intent] %s (confidence=%s)", intent, intent_result.get("confidence"))

    llm_entities = intent_result.get("entities", {})
    if llm_entities:
        eu = {}
        for f in ("term", "major", "difficulty_preference", "recommendation_goal"):
            if llm_entities.get(f):
                eu[f] = llm_entities[f]
        if eu:
            session = update_session(req.session_id, eu)

    memory_context = {
        "system_prompt_block": mem.system_prompt_block(user_id),
        "prefetched_context": mem.prefetch(req.message, user_id),
    }

    if intent == "off_topic":
        reply = generate_off_topic_response(req.message)
        add_message(req.session_id, "assistant", reply)
        mem.sync_turn(user_id, req.message, reply, req.session_id)
        _maybe_schedule_reflection(background_tasks, mem, req.session_id, user_id, session)
        return ChatResponse(reply=reply, intent=intent,
                            session_state=get_known_fields(req.session_id))

    if needs_clarification(session, intent):
        missing = detect_missing_fields(session, intent)
        reply = build_clarification_response(missing)
        add_message(req.session_id, "assistant", reply)
        mem.sync_turn(user_id, req.message, reply, req.session_id)
        _maybe_schedule_reflection(background_tasks, mem, req.session_id, user_id, session)
        return ChatResponse(reply=reply, intent=intent,
                            session_state=get_known_fields(req.session_id))

    state = get_known_fields(req.session_id)

    # ── Sync frontend's term to session state ──
    # The dropdown is authoritative for THIS turn — without this, the
    # downstream query falls back to state["term"] (often empty or stale)
    # and retrieves nothing, causing the LLM to hallucinate courses.
    if req.term and req.term != state.get("term"):
        update_session(req.session_id, {"term": req.term})
        state = get_known_fields(req.session_id)
        logger.info("[term-sync] frontend term %r written to session %s",
                    req.term, req.session_id)

    validation_dict = None                              # 新增：默认 None

    if intent == "single_query":
        reply, cards, followups = await _handle_single_query(
            req.message, state, memory_context,
            system_prompt=req.system_prompt,            # 新增
        )
    else:
        # ── 新增：把 session_id / term / system_prompt 传进去 ──
        reply, cards, followups, validation_dict = await _handle_recommendation(
            req.message, state, memory_context,
            session_id=req.session_id, term_str=req.term,
            system_prompt=req.system_prompt,            # 新增
        )

    add_message(req.session_id, "assistant", reply)
    mem.sync_turn(user_id, req.message, reply, req.session_id)
    _maybe_schedule_reflection(background_tasks, mem, req.session_id, user_id, session)

    return ChatResponse(
        reply=reply, cards=cards, followups=followups,
        intent=intent, session_state=state,
        pending_schedule=session.get("pending_schedule", []),
        validation_report=validation_dict,              # 新增
    )


def _maybe_schedule_reflection(
    background_tasks: BackgroundTasks,
    mem,
    session_id: str,
    user_id: str,
    session: dict,
) -> None:
    if mem.should_reflect(session_id):
        history_snapshot = list(session.get("history", []))[-12:]
        logger.info(
            "[Channel B] scheduling reflection for turn %d (history=%d msgs)",
            mem.turn_count(session_id), len(history_snapshot),
        )
        background_tasks.add_task(
            _run_reflection_task,
            user_id=user_id,
            history=history_snapshot,
        )


# ── Card builder ─────────────────────────────────────────

def _build_card(item: dict, state: dict) -> dict:
    c = item["course"]
    reasons = []
    major = state.get("major")
    if major and major in c.get("major_requirement", []):
        reasons.append(f"Counts toward {major}")
    grades = item.get("grade_distribution") or {}
    avg = grades.get("avg_gpa", 0)
    if avg >= 3.3:
        reasons.append(f"Generous grading (avg GPA {avg:.1f})")
    for sec in item.get("sections", []):
        pr = sec.get("professor_rating") or {}
        if pr.get("overall") and pr["overall"] >= 4.5:
            reasons.append(f"{sec['instructor']} rated {pr['overall']}/5")
            break
    return {
        "course_id": c["course_id"], "title": c["title"],
        "units": c["units"], "department": c.get("department", ""),
        "description": c.get("description", ""),
        "ge_category": c.get("ge_category"),
        "major_requirement": c.get("major_requirement", []),
        "prereq_met": item.get("prereq_met", True),
        "prereq_missing": item.get("prereq_missing", []),
        "has_conflict": item.get("has_conflict", False),
        "conflict_summary": item.get("conflict_summary", ""),
        "conflict_status":  item.get("conflict_status",  "none"),
        "grade_distribution": item.get("grade_distribution"),
        "sections": item.get("sections", []),
        "reason": ". ".join(reasons) if reasons else "Solid option.",
    }


async def _handle_recommendation(
    user_msg,
    state,
    memory_context=None,
    session_id=None,                                    # 新增
    term_str=None,                                      # 新增
    system_prompt=None,                                 # 新增
    on_token=None,                                      # 新增：流式回调
    # ── Phase 3.4 ─────────────────────────────────────
    recent_turns: Optional[list[dict]] = None,
    decisions: Optional[list[dict]] = None,
    summary: Optional[str] = None,
):
    from app.llm.adapter import generate_answer_llm
    results = query_course_recommendations(
        term=state.get("term", "Fall 2025"), major=state.get("major"),
        completed_courses=state.get("completed_courses", []),
        selected_courses=state.get("selected_courses", []),
        difficulty_preference=state.get("difficulty_preference"),
        recommendation_goal=state.get("recommendation_goal"),
    )
    # Empty / whitespace-only override → adapter falls back to default.
    sp_override = system_prompt.strip() if (system_prompt and system_prompt.strip()) else None

    if on_token is not None:
        # Streaming path — yield chunks to caller as they arrive.
        from app.llm.adapter import stream_answer_llm
        chunks: list[str] = []
        async for chunk in stream_answer_llm(
            user_msg, results, state,
            memory_context=memory_context,
            system_prompt_override=sp_override,
            recent_turns=recent_turns,
            decisions=decisions,
            summary=summary,
        ):
            chunks.append(chunk)
            await on_token(chunk)
        answer = "".join(chunks) or None
    else:
        # Non-streaming path (existing behavior).
        answer = await generate_answer_llm(
            user_msg, results, state,
            memory_context=memory_context,
            system_prompt_override=sp_override,             # 新增
            recent_turns=recent_turns,
            decisions=decisions,
            summary=summary,
        )

    if answer:
        all_candidates = results.get("primary", []) + results.get("flagged", [])
        by_id = {item["course"]["course_id"].upper(): item for item in all_candidates}
        cards = []
        for cid in _course_ids_in_order(answer):
            if cid in by_id:
                cards.append(_build_card(by_id[cid], state))
        if not cards:
            cards = [_build_card(i, state) for i in results.get("primary", [])[:3]]
    else:
        answer = generate_recommendation_answer(results, state)
        cards = [_build_card(i, state) for i in results.get("primary", [])]

    # ── Validation Phase 1 ─────────────────────────────────
    # Pick a target term in order of priority:
    #   1. req.term (frontend explicit)
    #   2. state["term"] (session state)
    #   3. registry.default() (latest loaded term — demo fallback)
    validation_dict = None
    target_term = (
        Term.parse(term_str or "")
        or Term.parse(state.get("term", ""))
    )
    catalog = get_catalog(target_term) if target_term else None
    # Demo fallback: when the asked term has no loaded data, use whatever
    # term IS loaded. Remove this fallback once you have multi-term data.
    if catalog is None:
        fallback_term = get_term_registry().default()
        if fallback_term:
            catalog = get_catalog(fallback_term)
            if catalog:
                logger.info(
                    "[validation] term %r has no data; falling back to %s",
                    state.get("term"), fallback_term.term_id,
                )

    if catalog and answer:
        ctx = ValidationContext(
            llm_answer=answer,
            retrieved=results,
            catalog=catalog,
            session_state=state,
            user_message=user_msg,
        )
        report = validate(ctx)
        action = decide_action(report)
        answer, cards, changed = apply_report(answer, cards, report, action)
        write_log(ctx, report, action, changed, session_id=session_id)
        validation_dict = report.to_dict()
        logger.info(
            "[validation] overall=%s errors=%d warnings=%d action=%s",
            report.overall, len(report.errors), len(report.warnings), action.value,
        )
    else:
        logger.info("[validation] skipped (no catalog or no answer)")
    # ───────────────────────────────────────────────────────

    followups = generate_followups(results, state, "course_recommendation")
    return answer, cards, followups, validation_dict


async def _handle_single_query(message, state, memory_context=None, system_prompt=None, on_token=None,
                               recent_turns: Optional[list[dict]] = None,
                               decisions: Optional[list[dict]] = None,
                               summary: Optional[str] = None):
    from app.llm.adapter import generate_answer_llm
    sp_override = system_prompt.strip() if (system_prompt and system_prompt.strip()) else None

    async def _call_llm(payload_data):
        """Run generate_answer_llm OR stream_answer_llm depending on on_token."""
        if on_token is None:
            return await generate_answer_llm(
                message, payload_data, state,
                memory_context=memory_context,
                system_prompt_override=sp_override,
                recent_turns=recent_turns,
                decisions=decisions,
                summary=summary,
            )
        from app.llm.adapter import stream_answer_llm
        chunks: list[str] = []
        async for chunk in stream_answer_llm(
            message, payload_data, state,
            memory_context=memory_context,
            system_prompt_override=sp_override,
            recent_turns=recent_turns,
            decisions=decisions,
            summary=summary,
        ):
            chunks.append(chunk)
            await on_token(chunk)
        return "".join(chunks) or None

    ml = message.lower()
    from app.data.mock_data import COURSES
    for c in COURSES:
        if c["course_id"].lower() in ml:
            data = query_single_course(c["course_id"], state.get("term"))
            if data:
                card = {
                    "course_id": data["course"]["course_id"],
                    "title": data["course"]["title"],
                    "units": data["course"]["units"],
                    "department": data["course"].get("department", ""),
                    "description": data["course"].get("description", ""),
                    "ge_category": data["course"].get("ge_category"),
                    "major_requirement": data["course"].get("major_requirement", []),
                    "prereq_met": True, "prereq_missing": [],
                    "has_conflict": False,
                    "grade_distribution": data.get("grade_distribution"),
                    "sections": data.get("sections", []),
                    "reason": "",
                }
                ans = await _call_llm(data)
                if not ans:
                    ans = generate_single_query_answer(data)
                    if on_token:
                        await on_token(ans)        # fallback also reaches the stream
                fu = generate_single_query_followups(c["course_id"], state)
                return ans, [card], fu
    from app.data.mock_data import PROFESSOR_RATINGS
    for name in PROFESSOR_RATINGS:
        if name.lower().split(",")[0] in ml:
            rating = query_professor(name)
            ans = await _call_llm({"professor": name, "rating": rating})
            if not ans:
                ans = generate_professor_answer(name, rating)
                if on_token:
                    await on_token(ans)
            return ans, [], []

    # ── Phase 3.4 polish: referential follow-up resolution ──
    # The user's current message has no explicit course ID or
    # professor name — but they're likely referring to something we
    # discussed earlier ("那个课怎么样" / "what about that course").
    #
    # Strategy:
    #   1. Scan recent_turns for the most recently mentioned course ID
    #   2. If found → run query_single_course on it so we get REAL
    #      grade distribution + sections (not LLM-fabricated stats)
    #   3. Pass the full data to the LLM, which now has both history
    #      and real data — produces a grounded answer + a course card
    #   4. If no course in history either → fall through to LLM with
    #      history alone, then to the hardcoded help message
    if recent_turns:
        referenced = _resolve_referenced_course(recent_turns)
        if referenced:
            data = query_single_course(referenced, state.get("term"))
            if data:
                logger.info("[single_query] referential resolve %r → %s (full data)",
                            message[:40], referenced)
                card = {
                    "course_id": data["course"]["course_id"],
                    "title": data["course"]["title"],
                    "units": data["course"]["units"],
                    "department": data["course"].get("department", ""),
                    "description": data["course"].get("description", ""),
                    "ge_category": data["course"].get("ge_category"),
                    "major_requirement": data["course"].get("major_requirement", []),
                    "prereq_met": True, "prereq_missing": [],
                    "has_conflict": False,
                    "grade_distribution": data.get("grade_distribution"),
                    "sections": data.get("sections", []),
                    "reason": "",
                }
                ans = await _call_llm(data)
                if ans:
                    fu = generate_single_query_followups(referenced, state)
                    return ans, [card], fu
                # LLM empty → fall through to history-only call

        # No course in history (or query returned None) — try LLM
        # with history alone. It may still produce a useful answer
        # for non-course follow-ups ("你刚才的建议靠谱吗").
        ans = await _call_llm({})
        if ans:
            return ans, [], []
        # else fall through to fallback

    fallback = ("I'm not sure which course or professor you mean. "
                "Try a course ID like ICS33 or a professor name.")
    if on_token:
        await on_token(fallback)
    return (fallback, [], [])


# ══════════════════════════════════════════════════════════
#  Streaming endpoint  /api/chat/stream
# ══════════════════════════════════════════════════════════
#
# Same logic as the /api/chat endpoint above, but the LLM-generated
# `reply` field is streamed back via Server-Sent Events instead of
# waiting for the full text. cards/followups/validation are sent as
# one final `meta` event.
#
# Why it matters:
#   - UX: user sees text appearing immediately (no "Send → 10s blank → big reply")
#   - Stop button: aborting the fetch closes the HTTP connection, FastAPI
#     cancels the producer task, the async iterator inside stream_answer_llm
#     gets CancelledError, AsyncOpenAI closes its connection to DeepSeek,
#     and DeepSeek stops generating tokens. No wasted API tokens.
#
# Wire format:
#   data: {"type": "token", "text": "<chunk>"}
#   data: {"type": "token", "text": "<chunk>"}
#   ...
#   data: {"type": "meta",  "cards": [...], "followups": [...], ...}
#   data: {"type": "done"}

from fastapi.responses import StreamingResponse


@router.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest, background_tasks: BackgroundTasks):
    return StreamingResponse(
        _stream_chat(req, background_tasks),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # tell nginx-like proxies not to buffer
        },
    )


async def _stream_chat(req: ChatRequest, background_tasks: BackgroundTasks):
    """Async generator yielding SSE-formatted events."""
    import asyncio
    import json as _json

    def sse(event: dict) -> str:
        return f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"

    queue: asyncio.Queue = asyncio.Queue()
    DONE = object()

    async def producer():
        """Run the full chat pipeline, pushing events into the queue."""
        try:
            mem = get_memory_manager()
            user_id = req.student_id or "demo_001"

            # ── Phase 3.3: resolve the request's session_id to a persistent one ──
            persistent_sid = _resolve_session_id(req.session_id, user_id, req.term)

            session = get_or_create_session(req.session_id)
            _hydrate_state_from_session(user_id, persistent_sid, session)
            if not session.get("major") and req.student_id:
                load_student_into_session(req.session_id, req.student_id)
                session = get_or_create_session(req.session_id)

            add_message(req.session_id, "user", req.message)
            mem.on_turn_start(req.session_id, user_id)
            logger.info("[stream turn %d] user=%s session=%s msg=%r",
                        mem.turn_count(req.session_id), user_id,
                        persistent_sid, req.message[:120])

            # Channel A
            extracted = await extract_info_from_message(req.message, session)
            if extracted:
                _capture_hard_facts(session, extracted, user_id, mem)
                if extracted:
                    session = update_session(req.session_id, extracted)

            intent_result = await classify_intent(req.message)
            intent = intent_result["intent"]
            logger.info("[stream intent] %s", intent)

            llm_entities = intent_result.get("entities", {})
            if llm_entities:
                eu = {f: llm_entities[f]
                      for f in ("term", "major", "difficulty_preference", "recommendation_goal")
                      if llm_entities.get(f)}
                if eu:
                    session = update_session(req.session_id, eu)

            memory_context = {
                "system_prompt_block": mem.system_prompt_block(user_id),
                "prefetched_context": mem.prefetch(req.message, user_id),
            }

            # ── Phase 3.4: load structured context layers from sessions.py ──
            try:
                session_meta = sessions_data.get_session_meta(user_id, persistent_sid)
                recent_turns = sessions_data.read_turns(user_id, persistent_sid)
                decisions    = session_meta.get("decisions") or []
                summary      = session_meta.get("summary")
            except sessions_data.SessionNotFound:
                session_meta = {}
                recent_turns = []
                decisions    = []
                summary      = None

            # ── Short paths: deliver whole reply at once ──
            if intent == "off_topic":
                reply = generate_off_topic_response(req.message)
                add_message(req.session_id, "assistant", reply)
                mem.sync_turn(user_id, req.message, reply, req.session_id)
                _persist_turn(user_id, persistent_sid, req.message, reply)
                _maybe_schedule_reflection(background_tasks, mem, req.session_id, user_id, session)
                await queue.put({"type": "token", "text": reply})
                await queue.put({
                    "type": "meta",
                    "session_id": persistent_sid,
                    "intent": intent,
                    "cards": [],
                    "followups": [],
                    "validation_report": None,
                    "session_state": get_known_fields(req.session_id),
                    "pending_schedule": session.get("pending_schedule", []),
                })
                return

            if needs_clarification(session, intent):
                missing = detect_missing_fields(session, intent)
                reply = build_clarification_response(missing)
                add_message(req.session_id, "assistant", reply)
                mem.sync_turn(user_id, req.message, reply, req.session_id)
                _persist_turn(user_id, persistent_sid, req.message, reply)
                _maybe_schedule_reflection(background_tasks, mem, req.session_id, user_id, session)
                await queue.put({"type": "token", "text": reply})
                await queue.put({
                    "type": "meta",
                    "session_id": persistent_sid,
                    "intent": intent,
                    "cards": [],
                    "followups": [],
                    "validation_report": None,
                    "session_state": get_known_fields(req.session_id),
                    "pending_schedule": session.get("pending_schedule", []),
                })
                return

            state = get_known_fields(req.session_id)
            if req.term and req.term != state.get("term"):
                update_session(req.session_id, {"term": req.term})
                state = get_known_fields(req.session_id)
                logger.info("[stream term-sync] %r written", req.term)

            # ── Stream the LLM answer through on_token ──
            async def on_token(text: str):
                await queue.put({"type": "token", "text": text})

            validation_dict = None
            if intent == "single_query":
                reply, cards, followups = await _handle_single_query(
                    req.message, state, memory_context,
                    system_prompt=req.system_prompt,
                    on_token=on_token,
                    recent_turns=recent_turns,
                    decisions=decisions,
                    summary=summary,
                )
            else:
                reply, cards, followups, validation_dict = await _handle_recommendation(
                    req.message, state, memory_context,
                    session_id=req.session_id, term_str=req.term,
                    system_prompt=req.system_prompt,
                    on_token=on_token,
                    recent_turns=recent_turns,
                    decisions=decisions,
                    summary=summary,
                )

            add_message(req.session_id, "assistant", reply)
            mem.sync_turn(user_id, req.message, reply, req.session_id)

            # ── Phase 3.3 + 3.5: persist turn to session, then detect decisions ──
            new_turn_index = _persist_turn(user_id, persistent_sid, req.message, reply)
            _detect_and_pin_decisions(user_id, persistent_sid, req.message, new_turn_index)

            _maybe_schedule_reflection(background_tasks, mem, req.session_id, user_id, session)

            await queue.put({
                "type": "meta",
                "session_id": persistent_sid,
                "intent": intent,
                "cards": cards,
                "followups": followups,
                "validation_report": validation_dict,
                "session_state": state,
                "pending_schedule": session.get("pending_schedule", []),
            })
        except asyncio.CancelledError:
            logger.info("[stream] producer cancelled (client disconnected)")
            raise
        except Exception as e:
            logger.exception("[stream] producer failed: %s", e)
            await queue.put({"type": "error", "message": str(e)})
        finally:
            await queue.put(DONE)

    task = asyncio.create_task(producer())
    try:
        while True:
            event = await queue.get()
            if event is DONE:
                yield sse({"type": "done"})
                break
            yield sse(event)
    except asyncio.CancelledError:
        # Client disconnected — cancel the producer so the LLM stream
        # closes its upstream connection and DeepSeek stops generating.
        logger.info("[stream] consumer cancelled, cascading to producer")
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        raise
    finally:
        if not task.done():
            task.cancel()


# ── Schedule endpoints ───────────────────────────────────

class ScheduleRequest(BaseModel):
    session_id: str = "demo_session"
    course_id: str
    section: str = "A"


@router.post("/schedule/add")
async def add_to_schedule(req: ScheduleRequest):
    session = get_or_create_session(req.session_id)
    entry = {"course_id": req.course_id, "section": req.section, "status": "pending"}
    existing_ids = [e["course_id"] for e in session.get("pending_schedule", [])]
    if req.course_id not in existing_ids:
        session.setdefault("pending_schedule", []).append(entry)
    events = _build_schedule_events(session)
    return {"ok": True, "pending_schedule": session["pending_schedule"], "events": events}


@router.post("/schedule/remove")
async def remove_from_schedule(req: ScheduleRequest):
    session = get_or_create_session(req.session_id)
    session["pending_schedule"] = [
        e for e in session.get("pending_schedule", []) if e["course_id"] != req.course_id
    ]
    events = _build_schedule_events(session)
    return {"ok": True, "pending_schedule": session["pending_schedule"], "events": events}


class EndSessionRequest(BaseModel):
    session_id: str = "demo_session"
    student_id: Optional[str] = "demo_001"


@router.post("/session/end")
async def end_session(req: EndSessionRequest):
    user_id = req.student_id or "anonymous"
    session = get_or_create_session(req.session_id)
    history = session.get("history", [])
    get_memory_manager().on_session_end(user_id, req.session_id, history)
    return {"ok": True, "messages_archived": len(history)}


DAY_MAP = {"M": "Mon", "Tu": "Tue", "W": "Wed", "Th": "Thu", "F": "Fri"}

def _parse_days(s):
    result, i = [], 0
    while i < len(s):
        if i+1 < len(s) and s[i:i+2] in DAY_MAP:
            result.append(DAY_MAP[s[i:i+2]]); i += 2
        elif s[i] in DAY_MAP:
            result.append(DAY_MAP[s[i]]); i += 1
        else:
            i += 1
    return result

def _build_schedule_events(session):
    from app.data.db import get_sections, get_course_info
    events = []
    for entry in session.get("pending_schedule", []):
        cid, sid = entry["course_id"], entry.get("section", "A")
        course = get_course_info(cid)
        sections = get_sections(cid, session.get("term", "Fall 2025"))
        sec = next((s for s in sections if s["section"] == sid), sections[0] if sections else None)
        if not sec:
            continue
        tp = sec["time"].split("-")
        if len(tp) != 2:
            continue
        for day in _parse_days(sec["days"]):
            events.append({
                "course_id": cid, "title": course["title"] if course else cid,
                "section": sec["section"], "instructor": sec["instructor"],
                "day": day, "start": tp[0].strip(), "end": tp[1].strip(),
                "location": sec.get("location", ""),
            })
    return events
