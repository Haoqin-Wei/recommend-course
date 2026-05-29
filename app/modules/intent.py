"""
Intent Classification Module

Maps to SKILL.md: Trigger Conditions / Non-Trigger Conditions.

Classifies user messages into:
  - "course_recommendation" → full skill flow
  - "single_query"          → simplified flow (no full profile needed)
  - "off_topic"             → templated decline

The keyword-list fast path that used to live here was removed once
the agent loop landed: the agent reads the raw message through its
own tools / system prompt, so a pre-agent keyword classifier became
both redundant and a source of false routing (e.g. a CS student
casually mentioning a club triggered "off_topic"). The remaining
path is:

  1. Structured commitment/decision regex (intent_rules.py) — pure
     deterministic patterns like "我决定选 X", "I'll take Y", drops,
     comparisons. These aren't keywords; they're shape-matchers that
     short-circuit obvious cases before paying for an LLM call.
  2. LLM classifier (classify_intent_llm in adapter.py) — handles
     everything else.
  3. Default fallback when the LLM is unavailable → assume
     course_recommendation so the agent loop still gets a chance.
"""


async def classify_intent(message: str) -> dict:
    """
    Classify a user message. Delegates to adapter.classify_intent_llm,
    which itself tries the structured-regex fast path first, then
    falls through to a real LLM call.

    Returns: {"intent": str, "confidence": float, "entities": dict,
              "source": str}. The shape stays stable for chat.py
    even when we default-route on LLM failure.
    """
    from app.llm.adapter import classify_intent_llm

    result = await classify_intent_llm(message)
    if result and "intent" in result:
        return {
            "intent":     result["intent"],
            "confidence": result.get("confidence", 0.9),
            "entities":   result.get("entities", {}),
            "source":     result.get("source", "llm"),
        }

    # LLM unavailable / returned nothing — pick the path that gives the
    # user the best shot at a useful answer rather than the templated
    # off_topic decline. The agent loop tolerates a misclassification
    # here because it routes on its own context once invoked.
    return {
        "intent":     "course_recommendation",
        "confidence": 0.0,
        "entities":   {},
        "source":     "default_fallback",
    }
