"""
Chat Router — orchestrates the SKILL.md pipeline.

Two-channel memory architecture:
    Channel A (immediate, every turn):
        extract_info_llm() pulls hard facts from the user's message.
        _capture_hard_facts() routes them:
          • course status (currently_taking / completed) → session lists + facts.json
          • identity (major / year / target_gpa / graduation_term) → profile.json

    Channel B (periodic, background):
        Every REFLECTION_INTERVAL turns (default 3), after the response is
        sent, FastAPI BackgroundTasks fires _run_reflection_task(). That task
        spawns an independent LLM call (reflect_on_history_llm) which
        examines recent history for SOFT patterns and writes them to
        preferences.json. Does NOT block user-facing latency.

LLM-driven card rendering:
    Cards are filtered to courses the LLM actually mentioned in its reply,
    in narrative order. Falls back to top-3 primary if the LLM names none.
"""

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

router = APIRouter()


# Loose course-ID regex for scanning LLM output. Permissive on purpose —
# we intersect matches with the known candidate pool, so false positives
# are filtered out automatically.
_COURSE_ID_SCAN = re.compile(
    r'\b[A-Z][A-Z0-9]{1,7}\d+[A-Z]?\b',
    re.IGNORECASE,
)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "demo_session"
    student_id: Optional[str] = "demo_001"


class ChatResponse(BaseModel):
    reply: str
    cards: list[dict] = []
    followups: list[str] = []
    intent: str = ""
    session_state: dict = {}
    pending_schedule: list[dict] = []


# ── Channel A: hard-fact capture (every turn) ────────────

def _merge_into_list(session: dict, field: str, items: list[str]) -> list[str]:
    """Append items to a session list, dedup case-insensitively. Returns new ones."""
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


# Identity fields that get mirrored into the long-term profile.
# Other extracted scalars (term, difficulty_preference, recommendation_goal)
# stay only in session — they're per-term, not stable identity.
_IDENTITY_FIELDS_FOR_PROFILE = ("major", "year", "target_gpa", "graduation_term")


def _capture_hard_facts(
    session: dict,
    extracted: dict,
    user_id: str,
    mem,
) -> None:
    """
    Channel A: pull every explicitly-stated fact out of `extracted` and route it.

    Mutates `extracted` (pops list/identity keys so update_session() doesn't
    redundantly process them).
    """
    # ── Course status: session lists + facts.json ──
    currently_taking = extracted.pop("currently_taking", None) or []
    completed = extracted.pop("completed", None) or []

    if currently_taking:
        new_courses = _merge_into_list(session, "selected_courses", currently_taking)
        if mem.provider:
            for c in new_courses:
                mem.provider.add_fact(user_id, f"Currently taking {c}")

    if completed:
        new_courses = _merge_into_list(session, "completed_courses", completed)
        if mem.provider:
            for c in new_courses:
                mem.provider.add_fact(user_id, f"Completed {c}")

    # ── Identity: long-term profile.json ──
    profile_updates = {}
    for f in _IDENTITY_FIELDS_FOR_PROFILE:
        # `major` and `year` are also session fields — read from extracted but
        # don't pop, so update_session() can mirror them into session state too.
        v = extracted.get(f) if f in ("major", "year") else extracted.pop(f, None)
        if v not in (None, "", []):
            profile_updates[f] = v
    if profile_updates and mem.provider:
        mem.provider.update_profile(user_id, profile_updates)


# ── Channel B: background reflection (every N turns) ─────

async def _run_reflection_task(user_id: str, history: list[dict]) -> None:
    """
    Fired as a FastAPI BackgroundTask AFTER the response is sent.
    Calls the reflection LLM, writes any new soft preferences.
    """
    from app.llm.adapter import reflect_on_history_llm
    mem = get_memory_manager()
    if not mem.provider:
        return
    existing = mem.get_preferences(user_id)
    new_prefs = await reflect_on_history_llm(history, existing)
    if not new_prefs:
        return
    for pref in new_prefs:
        mem.add_preference(user_id, pref)


# ── LLM-output scanner for card filtering ────────────────

def _course_ids_in_order(text: str) -> list[str]:
    """Return course-like tokens in the order they appear, deduped, uppercase."""
    seen = set()
    result = []
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

    # Phase 1: initialize memory for this session (idempotent)
    mem.initialize_session(req.session_id, user_id)

    session = get_or_create_session(req.session_id)
    if not session.get("major") and req.student_id:
        load_student_into_session(req.session_id, req.student_id)
        session = get_or_create_session(req.session_id)

    add_message(req.session_id, "user", req.message)

    # Phase 2 start: bump turn counter (no nudge text anymore)
    mem.on_turn_start(req.session_id, user_id)

    # Channel A: extract hard facts and route them
    extracted = await extract_info_from_message(req.message, session)
    if extracted:
        _capture_hard_facts(session, extracted, user_id, mem)
        if extracted:
            session = update_session(req.session_id, extracted)

    intent_result = await classify_intent(req.message)
    intent = intent_result["intent"]

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
    if intent == "single_query":
        reply, cards, followups = await _handle_single_query(req.message, state, memory_context)
    else:
        reply, cards, followups = await _handle_recommendation(req.message, state, memory_context)

    add_message(req.session_id, "assistant", reply)
    mem.sync_turn(user_id, req.message, reply, req.session_id)
    _maybe_schedule_reflection(background_tasks, mem, req.session_id, user_id, session)

    return ChatResponse(reply=reply, cards=cards, followups=followups,
                        intent=intent, session_state=state,
                        pending_schedule=session.get("pending_schedule", []))


def _maybe_schedule_reflection(
    background_tasks: BackgroundTasks,
    mem,
    session_id: str,
    user_id: str,
    session: dict,
) -> None:
    """If this turn is a reflection turn, schedule a background reflection task."""
    if mem.should_reflect(session_id):
        history_snapshot = list(session.get("history", []))[-12:]
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
        "grade_distribution": item.get("grade_distribution"),
        "sections": item.get("sections", []),
        "reason": ". ".join(reasons) if reasons else "Solid option.",
    }


async def _handle_recommendation(user_msg, state, memory_context=None):
    from app.llm.adapter import generate_answer_llm
    results = query_course_recommendations(
        term=state.get("term", "Fall 2025"), major=state.get("major"),
        completed_courses=state.get("completed_courses", []),
        selected_courses=state.get("selected_courses", []),
        difficulty_preference=state.get("difficulty_preference"),
        recommendation_goal=state.get("recommendation_goal"),
    )
    answer = await generate_answer_llm(user_msg, results, state, memory_context=memory_context)

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

    followups = generate_followups(results, state, "course_recommendation")
    return answer, cards, followups


async def _handle_single_query(message, state, memory_context=None):
    from app.llm.adapter import generate_answer_llm
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
                ans = await generate_answer_llm(message, data, state, memory_context=memory_context)
                if not ans:
                    ans = generate_single_query_answer(data)
                fu = generate_single_query_followups(c["course_id"], state)
                return ans, [card], fu
    from app.data.mock_data import PROFESSOR_RATINGS
    for name in PROFESSOR_RATINGS:
        if name.lower().split(",")[0] in ml:
            rating = query_professor(name)
            ans = await generate_answer_llm(message, {"professor": name, "rating": rating}, state, memory_context=memory_context)
            if not ans:
                ans = generate_professor_answer(name, rating)
            return ans, [], []
    return ("I'm not sure which course or professor you mean. "
            "Try a course ID like ICS33 or a professor name.", [], [])


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


# ── Phase 3: Session end endpoint ────────────────────────

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
