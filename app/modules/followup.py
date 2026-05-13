"""
Follow-Up Question Generation

Maps to SKILL.md: Step 5 — Generate Follow-Up Questions.

The chips rendered from these strings get sent verbatim as the user's
NEXT message when clicked. So they must be phrased from the **student's
perspective** (imperatives / short questions), not as the advisor offering.

❌ Bad:  "Want me to compare CS131 and CS132 side by side?"
        ↑ Reads as advisor speaking, but user sends it. Inverted.

✅ Good: "Compare CS131 and CS132 side by side"
        ↑ Reads as user requesting. Sends naturally.

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
    Produce 2–3 follow-up suggestions, phrased as if the student were
    speaking. Returns a list of short imperatives.
    """
    followups: list[str] = []
    primary = query_results.get("primary", [])
    flagged = query_results.get("flagged", [])

    # ── If we gave recommendations, suggest a side-by-side ──
    if len(primary) >= 2:
        c1 = primary[0]["course"]["course_id"]
        c2 = primary[1]["course"]["course_id"]
        followups.append(f"Compare {c1} and {c2} side by side")

    # ── Suggest conflict check if user already has a schedule ──
    if primary and session_state.get("selected_courses"):
        followups.append("Check if these conflict with my current schedule")

    # ── Suggest re-ranking by different criteria ──────────
    goal = session_state.get("recommendation_goal")
    if goal != "professor_quality":
        followups.append("Re-sort these by professor ratings")
    elif goal != "easy_gpa":
        followups.append("Rank these by easiest grading")

    # ── Suggest GE / requirement check ────────────────────
    if session_state.get("major") and not goal == "ge_fulfillment":
        followups.append("Find GE courses to fill my requirements")

    # ── Suggest more options if results were limited ──────
    total = query_results.get("total_found", 0)
    if total > 5:
        followups.append(f"Show me the other {total - len(primary)} options")

    # ── If flagged courses exist, offer to explain ────────
    if flagged:
        followups.append("Show the courses that didn't make the main list")

    # Return top 3
    return followups[:3]


def generate_single_query_followups(course_id: str, session_state: dict) -> list[str]:
    """Follow-ups for single-point queries — same user-perspective convention."""
    followups = [
        f"Find courses similar to {course_id}",
    ]
    if session_state.get("selected_courses"):
        followups.append(f"Check if {course_id} fits my schedule")
    followups.append("Give me a personalized recommendation for the term")
    return followups[:3]
