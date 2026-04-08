"""
Intent Classification Module

Maps to SKILL.md: Trigger Conditions / Non-Trigger Conditions.

Classifies user messages into:
  - "course_recommendation" → activate skill
  - "single_query"          → simplified skill flow (no full profile needed)
  - "off_topic"             → do not activate skill

Strategy:
  1. High-confidence keyword match → return immediately (fast path)
  2. Ambiguous / low-confidence → call LLM for classification
  3. LLM unavailable → fall back to keyword result
"""


# ── Keywords that indicate course-related intent ─────────
COURSE_KEYWORDS = [
    "course", "class", "recommend", "prerequisite", "prereq",
    "professor", "instructor", "schedule", "section", "enroll",
    "ge ", "ge requirement", "major requirement", "units", "credits",
    "easy", "gpa", "grade", "difficult", "workload", "rmp",
    "rate my professor", "conflict", "time slot", "plan",
    "next quarter", "next semester", "fall", "winter", "spring",
    "summer", "syllabus", "register", "waitlist",
    # Chinese keywords from SKILL.md examples
    "选课", "推荐", "先修", "教授", "课表", "学期", "专业",
    "水课", "拿分", "冲突", "排课",
]

# ── Keywords that signal single-point queries ────────────
SINGLE_QUERY_PATTERNS = [
    "does * have prerequisites",
    "what are the prereqs for",
    "how is professor",
    "rate professor",
    "is * a ge",
    "does * conflict",
    "先修要求", "教授评分",
]

# ── Keywords that signal off-topic ───────────────────────
OFF_TOPIC_KEYWORDS = [
    "weather", "food", "restaurant", "gym", "parking", "bus",
    "housing", "dorm", "internship", "resume", "career fair",
    "study tips", "how to study", "club", "fraternity",
    "agent", "skill", "tool", "api", "code", "programming tutorial",
]


def classify_intent_rules(message: str) -> dict:
    """
    Rule-based intent classification (fast path).
    Returns result with confidence score.
    """
    msg_lower = message.lower()

    # Check off-topic first
    for kw in OFF_TOPIC_KEYWORDS:
        if kw in msg_lower:
            return {
                "intent": "off_topic",
                "confidence": 0.7,
                "matched_keywords": [kw],
            }

    # Check for single-point query patterns
    for pattern in SINGLE_QUERY_PATTERNS:
        core = pattern.replace("*", "")
        if core.strip() in msg_lower:
            return {
                "intent": "single_query",
                "confidence": 0.8,
                "matched_keywords": [pattern],
            }

    # Check for course-related keywords
    matched = [kw for kw in COURSE_KEYWORDS if kw in msg_lower]
    if matched:
        return {
            "intent": "course_recommendation",
            "confidence": min(0.5 + 0.1 * len(matched), 1.0),
            "matched_keywords": matched,
        }

    # No keywords matched — ambiguous
    return {
        "intent": "off_topic",
        "confidence": 0.3,
        "matched_keywords": [],
    }


async def classify_intent(message: str) -> dict:
    """
    Classify intent with LLM fallback for ambiguous messages.

    Flow:
      1. Run keyword rules — if confidence >= 0.7, return immediately
      2. Otherwise, try LLM classification
      3. If LLM fails, return the keyword result as-is
    """
    from app.llm.adapter import classify_intent_llm

    rules_result = classify_intent_rules(message)

    # High-confidence keyword match → skip LLM
    if rules_result["confidence"] >= 0.7:
        return rules_result

    # Ambiguous → try LLM
    llm_result = await classify_intent_llm(message)
    if llm_result and "intent" in llm_result:
        return {
            "intent": llm_result["intent"],
            "confidence": llm_result.get("confidence", 0.9),
            "matched_keywords": [],
            "entities": llm_result.get("entities", {}),
            "source": "llm",
        }

    # LLM unavailable → return keyword result
    return rules_result
