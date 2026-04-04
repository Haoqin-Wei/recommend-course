"""
Follow-Up Question Generation

Maps to SKILL.md: Step 5 — Generate Follow-Up Questions.

Directions per SKILL.md:
  - Narrow down further
  - Compare two candidates
  - Check time conflicts
  - Check GE / major requirement satisfaction
  - Continue optimizing by user preference

Generate 2–3 contextual follow-ups based on the current results and state.
"""


def generate_followups(
    query_results: dict,
    session_state: dict,
    intent: str,
) -> list[str]:
    """
    Produce 2–3 follow-up question suggestions.
    Returns a list of natural-language questions.
    """
    followups = []
    primary = query_results.get("primary", [])
    flagged = query_results.get("flagged", [])

    # ── If we gave recommendations, suggest comparisons ───
    if len(primary) >= 2:
        c1 = primary[0]["course"]["course_id"]
        c2 = primary[1]["course"]["course_id"]
        followups.append(
            f"Want me to compare {c1} and {c2} side by side?"
        )

    # ── Suggest conflict check if not yet done ────────────
    if primary and session_state.get("selected_courses"):
        followups.append(
            "Should I check if these recommendations conflict with your current schedule?"
        )

    # ── Suggest re-ranking by different criteria ──────────
    goal = session_state.get("recommendation_goal")
    if goal != "professor_quality":
        followups.append(
            "Want me to re-sort these by professor ratings instead?"
        )
    elif goal != "easy_gpa":
        followups.append(
            "Would you like me to rank these by easiest grading?"
        )

    # ── Suggest GE / requirement check ────────────────────
    if session_state.get("major") and not goal == "ge_fulfillment":
        followups.append(
            "I can also find GE courses to fill general education requirements — interested?"
        )

    # ── Suggest more options if results were limited ──────
    total = query_results.get("total_found", 0)
    if total > 5:
        followups.append(
            f"I found {total} options total — want me to show more?"
        )

    # ── If flagged courses exist, offer to explain ────────
    if flagged:
        followups.append(
            "Some courses didn't make the main list due to prereqs or conflicts. Want to see them anyway?"
        )

    # Return top 3
    return followups[:3]


def generate_single_query_followups(course_id: str, session_state: dict) -> list[str]:
    """Follow-ups for single-point queries."""
    followups = [
        f"Want me to find courses similar to {course_id}?",
    ]
    if session_state.get("selected_courses"):
        followups.append(
            f"Should I check if {course_id} fits into your current schedule?"
        )
    followups.append(
        "Would you like a full personalized recommendation based on your major and preferences?"
    )
    return followups[:3]
