"""
LLM Adapter — Placeholder for Claude Opus 4.6

This module wraps all LLM calls behind a single interface.
The demo uses simple rule-based fallbacks. When ready, swap in
real Claude API calls without changing the rest of the codebase.

TODO: Implement with Anthropic Python SDK
  pip install anthropic
  import anthropic
  client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
"""

from typing import Optional


# ── Configuration ────────────────────────────────────────

LLM_MODEL = "claude-opus-4-6"  # Target model for production
LLM_ENABLED = False  # Flip to True once API key is configured


async def chat_completion(
    system_prompt: str,
    user_message: str,
    context: Optional[dict] = None,
) -> str:
    """
    Send a message to the LLM and return the response text.

    Args:
        system_prompt: System-level instruction (skill behavior, persona).
        user_message:  The user's latest message.
        context:       Optional dict with session state, history, etc.

    Returns:
        Generated response text.

    TODO: Replace with real API call:
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=build_messages(user_message, context),
        )
        return response.content[0].text
    """
    # For the demo, this function is NOT called.
    # All logic is handled by rule-based modules.
    return "[LLM response placeholder — not connected]"


async def classify_intent_llm(user_message: str) -> dict:
    """
    Use the LLM to classify intent when rule-based detection is ambiguous.

    TODO: Implement with a structured prompt that returns JSON:
      {"is_course_related": bool, "intent_type": str, "entities": {...}}
    """
    return {"is_course_related": True, "intent_type": "unknown", "confidence": 0.0}


async def generate_answer_llm(
    user_message: str,
    retrieved_data: dict,
    session_state: dict,
) -> str:
    """
    Use the LLM to generate a natural-language recommendation answer
    following SKILL.md answer structure:
      1. Conclusion first
      2. Reasons
      3. Risk warnings
      4. Alternatives
      5. Follow-up questions

    TODO: Build prompt from retrieved_data + session_state,
          call chat_completion with the skill system prompt.
    """
    return "[LLM-generated answer placeholder]"
