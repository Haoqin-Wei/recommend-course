"""
Diagnostic #2 — call stream_answer_llm the way chat.py does.

The previous diagnostic (test_llm.py) called with positional args only,
which made `_build_messages_for_llm` take the LEGACY single-string path.
That worked (212 chunks).

This script passes recent_turns=[], decisions=[], summary=None — exactly
what chat.py's _handle_single_query._call_llm passes on a fresh session.
That triggers the NEW 6-layer context_builder path. If that path is what's
breaking, this script will yield 0 chunks like the server does.

Usage:
    .venv/bin/python3 scripts/test_llm_chatpath.py
"""
import asyncio
import json
import sys
import traceback

from app.llm import adapter


def banner(text: str) -> None:
    print(f"\n── {text} " + "─" * (60 - len(text)))


async def main_async():
    # ── Step 1: peek at what _build_messages_for_llm produces ──
    banner("Built messages")
    try:
        messages = adapter._build_messages_for_llm(
            user_message="我决定选 CS122A",
            retrieved_data={
                "course": {
                    "course_id": "CS122A",
                    "title": "Introduction to Data Management",
                    "units": 4,
                    "description": "Introduction to databases and data management.",
                },
                "grade_distribution": {"avg_gpa": 3.14, "pct_A": 40.2},
                "sections": [],
            },
            session_state={
                "major": "Computer Science",
                "year": "sophomore",
                "term": "Spring 2026",
                "completed_courses": ["ICS31", "ICS32"],
                "selected_courses": ["ICS33"],
            },
            memory_context=None,
            system_prompt_override=None,
            recent_turns=[],     # ← critical: triggers new-path
            decisions=[],
            summary=None,
        )
    except Exception:
        print("❌ _build_messages_for_llm raised an exception:")
        traceback.print_exc()
        return -1

    print(f"messages list length: {len(messages)}")
    for i, m in enumerate(messages):
        role = m.get("role", "?")
        content = m.get("content", "")
        preview = content[:200].replace("\n", " ") if isinstance(content, str) else repr(content)[:200]
        print(f"  [{i}] role={role}  len={len(content) if isinstance(content, str) else 'NA'}")
        print(f"      preview: {preview!r}")

    if not messages:
        print("⚠️  messages is empty — DeepSeek will reject this.")
        return 0

    # Sanity: must have at least one user-role message or DeepSeek won't generate
    roles = [m.get("role") for m in messages]
    if "user" not in roles:
        print("⚠️  no 'user' role in messages — DeepSeek requires at least one.")

    # ── Step 2: call stream_answer_llm with same params ──
    banner("Calling stream_answer_llm (new-path)")
    chunk_count = 0
    try:
        async for chunk in adapter.stream_answer_llm(
            user_message="我决定选 CS122A",
            retrieved_data={
                "course": {
                    "course_id": "CS122A",
                    "title": "Introduction to Data Management",
                    "units": 4,
                    "description": "Introduction to databases and data management.",
                },
                "grade_distribution": {"avg_gpa": 3.14, "pct_A": 40.2},
                "sections": [],
            },
            session_state={
                "major": "Computer Science",
                "year": "sophomore",
                "term": "Spring 2026",
                "completed_courses": ["ICS31", "ICS32"],
                "selected_courses": ["ICS33"],
            },
            memory_context=None,
            system_prompt_override=None,
            recent_turns=[],
            decisions=[],
            summary=None,
        ):
            chunk_count += 1
            if chunk_count <= 3:
                print(f"  [chunk {chunk_count}] {chunk!r}")
            elif chunk_count == 4:
                print("  [chunk 4] ... (suppressing further)")
    except Exception:
        print("❌ exception during streaming:")
        traceback.print_exc()
        return -2

    banner("Result")
    if chunk_count == 0:
        print("⚠️  TOTAL CHUNKS: 0 — new-path produces no output.")
        print("    The messages above show what was sent. Look for:")
        print("    - missing 'user' role")
        print("    - very long content that exceeds context window")
        print("    - malformed structure")
    else:
        print(f"✅ TOTAL CHUNKS: {chunk_count} — new-path also works.")
        print("    Issue must be even more specific (memory_context / system_prompt_override).")
    return chunk_count


def main() -> int:
    print(f"LLM_ENABLED: {adapter.LLM_ENABLED}, Model: {adapter.LLM_MODEL}")
    return asyncio.run(main_async()) or 0


if __name__ == "__main__":
    sys.exit(main())