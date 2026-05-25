"""
Verify that the data flowing to the LLM is real — not hallucinated.

Usage:
    python scripts/verify_data.py sections CS122A "Spring 2026"
    python scripts/verify_data.py course CS122A
    python scripts/verify_data.py instructor thornton
    python scripts/verify_data.py grades CS122A
    python scripts/verify_data.py conflict CS122A ICS46 "Spring 2026"
    python scripts/verify_data.py trace "Spring 2026 的 CS122A 谁教？" "Spring 2026"

Each command runs the SAME function the LLM tools call, then prints
the raw response. Compare with the LLM's natural-language answer to
the same question — every field the LLM mentions should be present
verbatim in this output.

The `trace` command goes further: it runs the full agent loop and
prints every tool call + every raw tool response + the LLM's final
text, so you can audit the whole reasoning chain end-to-end.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Make `import app.*` work whether you run from project root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _dump(label: str, obj) -> None:
    print(f"\n========== {label} ==========")
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def cmd_sections(course_id: str, term: str) -> None:
    from app.data import db
    r = db.get_sections(course_id, term)
    _dump(f"db.get_sections({course_id!r}, {term!r})", r)
    print(f"\nsource={r.get('source')}  found={r.get('found')}  "
          f"n_sections={len(r.get('sections', []))}")


def cmd_course(course_id: str) -> None:
    from app.data import db
    _dump(f"db.get_course_info({course_id!r})", db.get_course_info(course_id))


def cmd_instructor(name: str) -> None:
    from app.data import db
    _dump(f"db.get_professor_rating({name!r})", db.get_professor_rating(name))


def cmd_grades(course_id: str) -> None:
    from app.data import db
    _dump(f"db.get_grade_distribution({course_id!r})",
          db.get_grade_distribution(course_id))


def cmd_conflict(a: str, b: str, term: str) -> None:
    from app.agent.tools import dispatch
    r = dispatch("check_section_conflict",
                 {"course_a": a, "course_b": b, "term": term},
                 context={"user_id": "verify_cli", "term": term})
    _dump(f"check_section_conflict({a!r}, {b!r}, {term!r})", r)


async def cmd_trace(question: str, term: str) -> None:
    """Run the full agent loop and dump every tool call + tool response.

    This is the most thorough verification: you see EXACTLY what the
    LLM saw before producing its answer. If the LLM's natural-language
    answer mentions a fact that doesn't appear in any tool response
    here, that fact was hallucinated.
    """
    from app.llm.adapter import stream_agent_response
    from app.agent import tools as agent_tools

    print(f"\n========== AGENT TRACE ==========")
    print(f"question: {question!r}")
    print(f"term:     {term!r}")

    answer = ""
    tool_history: list[dict] = []

    async for ev in stream_agent_response(
        question,
        session_state={"major": "Computer Science",
                       "year": "junior",
                       "term": term},
        user_id="verify_cli",
        term=term,
    ):
        t = ev.get("type")
        if t == "token":
            answer += ev.get("text", "")
        elif t == "tool_call_start":
            name = ev.get("name")
            args = ev.get("args") or {}
            # Re-dispatch the SAME call locally so we can also print
            # the raw response (the stream itself only emits start/done
            # events, not the result body).
            result = agent_tools.dispatch(
                name, args,
                context={"user_id": "verify_cli", "term": term},
            )
            tool_history.append({"call": name, "args": args, "result": result})
        elif t == "error":
            print(f"\n[ERROR] {ev.get('message')}")

    for i, h in enumerate(tool_history, 1):
        print(f"\n--- TOOL CALL #{i}: {h['call']}({h['args']}) ---")
        print(json.dumps(h["result"], indent=2, ensure_ascii=False, default=str)[:2000])

    print(f"\n========== LLM FINAL ANSWER ({len(answer)} chars) ==========")
    print(answer)
    print(f"\n========== AUDIT GUIDE ==========")
    print("For every named instructor, section code, time, location, or")
    print("seat count in the LLM answer above, grep the tool responses")
    print("to confirm it's literal — not invented.")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_sec = sub.add_parser("sections");    p_sec.add_argument("course"); p_sec.add_argument("term")
    p_crs = sub.add_parser("course");      p_crs.add_argument("course")
    p_ins = sub.add_parser("instructor");  p_ins.add_argument("name")
    p_grd = sub.add_parser("grades");      p_grd.add_argument("course")
    p_cnf = sub.add_parser("conflict");    p_cnf.add_argument("a"); p_cnf.add_argument("b"); p_cnf.add_argument("term")
    p_trc = sub.add_parser("trace");       p_trc.add_argument("question"); p_trc.add_argument("term")
    args = ap.parse_args()

    if args.cmd == "sections":   cmd_sections(args.course, args.term)
    elif args.cmd == "course":    cmd_course(args.course)
    elif args.cmd == "instructor":cmd_instructor(args.name)
    elif args.cmd == "grades":    cmd_grades(args.course)
    elif args.cmd == "conflict":  cmd_conflict(args.a, args.b, args.term)
    elif args.cmd == "trace":     asyncio.run(cmd_trace(args.question, args.term))


if __name__ == "__main__":
    main()
