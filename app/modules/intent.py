"""
Intent Classification Module

Maps to SKILL.md: Trigger Conditions / Non-Trigger Conditions.

Classifies user messages into:
  - "course_recommendation" → activate skill
  - "single_query"          → simplified skill flow (no full profile needed)
  - "off_topic"             → do not activate skill

Strategy:
  0. Structured commitment/decision regex (intent_rules.py) — deterministic,
     covers "我决定选 CS122A", "I'll take CS161", drops, comparisons.
  1. Course-ID pattern match → strongest course-related signal (e.g. STAT67, CS122A)
  2. High-confidence keyword match → return immediately (fast path)
  3. Ambiguous / low-confidence → call LLM for classification
  4. LLM unavailable → fall back to keyword result
"""

import re


# ── Course ID pattern ────────────────────────────────────
# Matches course codes like CS33, ICS33, STAT67, CS122A, IN4MATX43,
# ANTHRO2A, WRITING39C, MATH2A, ECON15A.
#
# IMPORTANT: uses (?<![A-Za-z0-9]) / (?![A-Za-z0-9]) instead of \b
# because Python's regex \b is Unicode-aware — Chinese characters are
# classified as "word" characters by default, so \b between 选 and CS
# does NOT match in "我决定选CS122A". The look-arounds below say "not
# preceded / followed by an ASCII letter or digit" — Chinese characters
# are fine as neighbors.
COURSE_ID_PATTERN = re.compile(
    r'(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9]{1,7}\d{2,3}[A-Z]?|[A-Z]{3,8}\d[A-Z]?)(?![A-Za-z0-9])',
    re.IGNORECASE,
)


# ── Keywords that indicate course-related intent ─────────
COURSE_KEYWORDS = [
    "course", "class", "recommend", "prerequisite", "prereq",
    "professor", "instructor", "schedule", "section", "enroll",
    # Status verbs the user is likely to use
    "taking", "took", "passed", "completed", "finished", "currently in",
    "ge ", "ge requirement", "major requirement", "units", "credits",
    "easy", "gpa", "grade", "difficult", "workload", "rmp",
    "rate my professor", "conflict", "time slot", "plan",
    "next quarter", "next semester", "fall", "winter", "spring",
    "summer", "syllabus", "register", "waitlist",
    # Chinese keywords from SKILL.md examples
    "选课", "推荐", "先修", "教授", "课表", "学期", "专业",
    "水课", "拿分", "冲突", "排课",
    "正在上", "已修", "选了", "选过", "上过",
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

    Layering (most specific first):
      0. Structured commitment/decision regex (intent_rules.py) — explicit
         multi-language patterns like "我决定选 X", "I'll take Y", drops,
         comparisons. Catches commitments BEFORE the broader Course-ID
         match below so that "我决定选 CS122A" routes to single_query
         (focused analysis) rather than course_recommendation (which
         would query 10 candidates for the term — not what the user wants
         after they've already decided).
      1. Off-topic keywords — unambiguous non-course questions.
      2. Course-ID pattern — anything with a course code is course-related.
      3. Single-point query patterns.
      4. General course-related keywords.
      5. No match → off_topic with low confidence (falls through to LLM).
    """
    # ── Layer 0: structured commitment/decision rules ─────
    try:
        from app.llm import intent_rules
        rule_result = intent_rules.classify_by_rules(message)
        if rule_result:
            return {
                "intent": rule_result["intent"],
                "confidence": 0.95,
                "matched_keywords": [f"rule:{rule_result.get('rule_id')}"],
                "entities": rule_result.get("entities", {}),
                "source": "structured_rule",
            }
    except Exception:
        # Don't let a regex bug kill the chain — fall through silently.
        pass

    msg_lower = message.lower()

    # 1. Off-topic keywords first — these are unambiguous
    for kw in OFF_TOPIC_KEYWORDS:
        if kw in msg_lower:
            return {
                "intent": "off_topic",
                "confidence": 0.7,
                "matched_keywords": [kw],
            }

    # 2. Course-ID pattern — a course code is a near-certain course-related signal,
    #    even when the message has no other keywords (e.g. "I'm taking STAT67").
    course_id_match = COURSE_ID_PATTERN.search(message)
    if course_id_match:
        return {
            "intent": "course_recommendation",
            "confidence": 0.85,
            "matched_keywords": [f"course_id:{course_id_match.group()}"],
        }

    # 3. Single-point query patterns
    for pattern in SINGLE_QUERY_PATTERNS:
        core = pattern.replace("*", "")
        if core.strip() in msg_lower:
            return {
                "intent": "single_query",
                "confidence": 0.8,
                "matched_keywords": [pattern],
            }

    # 4. General course-related keywords
    matched = [kw for kw in COURSE_KEYWORDS if kw in msg_lower]
    if matched:
        return {
            "intent": "course_recommendation",
            "confidence": min(0.5 + 0.1 * len(matched), 1.0),
            "matched_keywords": matched,
        }

    # 5. No keywords matched — ambiguous, will fall through to LLM
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
