"""
Chat Router — API endpoint that orchestrates the SKILL.md pipeline.

Flow:
  1. Receive user message + session_id
  2. Extract info from message → update session state        (Step 1)
  3. Classify intent                                          (Trigger check)
  4. If off_topic → return off-topic response
  5. If course-related, check if clarification needed         (Step 2)
  6. If info sufficient → query data layer                    (Step 3)
  7. Generate answer                                          (Step 4)
  8. Append follow-up questions                               (Step 5)
  9. Return response + updated schedule state
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.modules.intent import classify_intent
from app.modules.state import (
    get_or_create_session,
    update_session,
    add_message,
    load_student_into_session,
    get_known_fields,
)
from app.modules.clarification import (
    detect_missing_fields,
    needs_clarification,
    build_clarification_response,
    extract_info_from_message,
)
from app.modules.query import (
    query_course_recommendations,
    query_single_course,
    query_professor,
)
from app.modules.answer import (
    generate_recommendation_answer,
    generate_single_query_answer,
    generate_professor_answer,
    generate_off_topic_response,
)
from app.modules.followup import (
    generate_followups,
    generate_single_query_followups,
)

router = APIRouter()


# ── Request / Response models ────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "demo_session"
    student_id: Optional[str] = "demo_001"  # Pre-filled for demo


class ChatResponse(BaseModel):
    reply: str
    followups: list[str] = []
    intent: str = ""
    session_state: dict = {}
    pending_schedule: list[dict] = []  # For frontend schedule panel


# ── Main chat endpoint ───────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session = get_or_create_session(req.session_id)

    # Load student profile into session on first message
    if not session.get("major") and req.student_id:
        load_student_into_session(req.session_id, req.student_id)
        session = get_or_create_session(req.session_id)

    # Record user message
    add_message(req.session_id, "user", req.message)

    # ── Step 1: Extract info from message ─────────────────
    extracted = extract_info_from_message(req.message, session)
    if extracted:
        session = update_session(req.session_id, extracted)

    # ── Trigger check: classify intent ────────────────────
    intent_result = classify_intent(req.message)
    intent = intent_result["intent"]

    # ── Off-topic ─────────────────────────────────────────
    if intent == "off_topic":
        reply = generate_off_topic_response(req.message)
        add_message(req.session_id, "assistant", reply)
        return ChatResponse(
            reply=reply,
            intent=intent,
            session_state=get_known_fields(req.session_id),
        )

    # ── Step 2: Clarification check ──────────────────────
    if needs_clarification(session, intent):
        missing = detect_missing_fields(session, intent)
        reply = build_clarification_response(missing)
        add_message(req.session_id, "assistant", reply)
        return ChatResponse(
            reply=reply,
            intent=intent,
            session_state=get_known_fields(req.session_id),
        )

    # ── Step 3 & 4: Query + Answer ────────────────────────
    state = get_known_fields(req.session_id)

    if intent == "single_query":
        reply, followups = _handle_single_query(req.message, state)
    else:
        reply, followups = _handle_recommendation(state)

    add_message(req.session_id, "assistant", reply)

    return ChatResponse(
        reply=reply,
        followups=followups,
        intent=intent,
        session_state=state,
        pending_schedule=session.get("pending_schedule", []),
    )


# ── Handlers ─────────────────────────────────────────────

def _handle_recommendation(state: dict) -> tuple[str, list[str]]:
    """Full recommendation flow (Steps 3–5)."""
    results = query_course_recommendations(
        term=state.get("term", "Fall 2025"),
        major=state.get("major"),
        completed_courses=state.get("completed_courses", []),
        selected_courses=state.get("selected_courses", []),
        difficulty_preference=state.get("difficulty_preference"),
        recommendation_goal=state.get("recommendation_goal"),
    )

    answer = generate_recommendation_answer(results, state)
    followups = generate_followups(results, state, "course_recommendation")

    # Append follow-ups to the answer text
    if followups:
        answer += "\n\n---\n**Want to keep going?**\n"
        for fq in followups:
            answer += f"- {fq}\n"

    return answer, followups


def _handle_single_query(message: str, state: dict) -> tuple[str, list[str]]:
    """Simplified single-point query flow."""
    msg_lower = message.lower()

    # Try to detect a course ID in the message
    # TODO: Use NER or LLM extraction for production
    from app.data.mock_data import COURSES
    for c in COURSES:
        if c["course_id"].lower() in msg_lower:
            data = query_single_course(c["course_id"], state.get("term"))
            answer = generate_single_query_answer(data)
            followups = generate_single_query_followups(c["course_id"], state)
            if followups:
                answer += "\n\n---\n"
                for fq in followups:
                    answer += f"- {fq}\n"
            return answer, followups

    # Try professor name
    from app.data.mock_data import PROFESSOR_RATINGS
    for name in PROFESSOR_RATINGS:
        if name.lower().split(",")[0] in msg_lower:
            rating = query_professor(name)
            answer = generate_professor_answer(name, rating)
            return answer, []

    # Fallback
    return (
        "I'm not sure which specific course or professor you're asking about. "
        "Could you give me the course ID (like ICS33) or professor name?",
        [],
    )


# ── Schedule management (for frontend dynamic schedule) ──

class AddToScheduleRequest(BaseModel):
    session_id: str = "demo_session"
    course_id: str
    section: str = "A"


@router.post("/schedule/add")
async def add_to_schedule(req: AddToScheduleRequest):
    """Add a course to the pending schedule (SKILL.md: a2ui / dynamic schedule)."""
    session = get_or_create_session(req.session_id)
    # TODO: Check for conflicts before adding
    entry = {"course_id": req.course_id, "section": req.section, "status": "pending"}

    # Avoid duplicates
    existing_ids = [e["course_id"] for e in session.get("pending_schedule", [])]
    if req.course_id not in existing_ids:
        session.setdefault("pending_schedule", []).append(entry)

    return {"ok": True, "pending_schedule": session["pending_schedule"]}


@router.post("/schedule/remove")
async def remove_from_schedule(req: AddToScheduleRequest):
    """Remove a course from the pending schedule."""
    session = get_or_create_session(req.session_id)
    session["pending_schedule"] = [
        e for e in session.get("pending_schedule", [])
        if e["course_id"] != req.course_id
    ]
    return {"ok": True, "pending_schedule": session["pending_schedule"]}
