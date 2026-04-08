"""
Chat Router — orchestrates the SKILL.md pipeline.

Frontend data contract — ChatResponse JSON:
  reply            str       Markdown-ish text answer
  cards            [Card]    Structured course recommendation cards (may be [])
  followups        [str]     Suggested follow-up questions
  intent           str       "course_recommendation" | "single_query" | "off_topic"
  session_state    dict      Current known fields
  pending_schedule [Entry]   Courses in the pending schedule

Card schema:
  course_id, title, units, department, description,
  ge_category, major_requirement[], prereq_met, prereq_missing[],
  has_conflict, grade_distribution{}, sections[], reason

Section schema:
  section, instructor, days, time, location, seats_open, professor_rating{}

Schedule event schema (returned by /schedule/add and /schedule/remove):
  course_id, title, section, instructor, day, start, end, location
"""

from fastapi import APIRouter
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

router = APIRouter()


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


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session = get_or_create_session(req.session_id)
    if not session.get("major") and req.student_id:
        load_student_into_session(req.session_id, req.student_id)
        session = get_or_create_session(req.session_id)

    add_message(req.session_id, "user", req.message)

    extracted = await extract_info_from_message(req.message, session)
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

    if intent == "off_topic":
        reply = generate_off_topic_response(req.message)
        add_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, intent=intent,
                            session_state=get_known_fields(req.session_id))

    if needs_clarification(session, intent):
        missing = detect_missing_fields(session, intent)
        reply = build_clarification_response(missing)
        add_message(req.session_id, "assistant", reply)
        return ChatResponse(reply=reply, intent=intent,
                            session_state=get_known_fields(req.session_id))

    state = get_known_fields(req.session_id)
    if intent == "single_query":
        reply, cards, followups = await _handle_single_query(req.message, state)
    else:
        reply, cards, followups = await _handle_recommendation(req.message, state)

    add_message(req.session_id, "assistant", reply)
    return ChatResponse(reply=reply, cards=cards, followups=followups,
                        intent=intent, session_state=state,
                        pending_schedule=session.get("pending_schedule", []))


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


async def _handle_recommendation(user_msg, state):
    from app.llm.adapter import generate_answer_llm
    results = query_course_recommendations(
        term=state.get("term", "Fall 2025"), major=state.get("major"),
        completed_courses=state.get("completed_courses", []),
        selected_courses=state.get("selected_courses", []),
        difficulty_preference=state.get("difficulty_preference"),
        recommendation_goal=state.get("recommendation_goal"),
    )
    cards = [_build_card(i, state) for i in results.get("primary", [])]
    answer = await generate_answer_llm(user_msg, results, state)
    if not answer:
        answer = generate_recommendation_answer(results, state)
    followups = generate_followups(results, state, "course_recommendation")
    return answer, cards, followups


async def _handle_single_query(message, state):
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
                ans = await generate_answer_llm(message, data, state)
                if not ans:
                    ans = generate_single_query_answer(data)
                fu = generate_single_query_followups(c["course_id"], state)
                return ans, [card], fu
    from app.data.mock_data import PROFESSOR_RATINGS
    for name in PROFESSOR_RATINGS:
        if name.lower().split(",")[0] in ml:
            rating = query_professor(name)
            ans = await generate_answer_llm(message, {"professor": name, "rating": rating}, state)
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
