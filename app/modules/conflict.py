"""
Section Time-Conflict Detection (Phase 2.8).

Determines whether two sections share a meeting day with overlapping
clock times. Uses the columns produced by `fetch_uci_data.py websoc`:

    days        e.g. "TuTh", "MWF", "F", "MTuWThF"
    start_time  e.g. "11:00"  (24-hour HH:MM)
    end_time    e.g. "12:20"
    time_is_tba "true" | "false" (string boolean from CSV)

Multi-meeting sections (e.g. Lec MWF + Lab Th) are <1% of the data and
already represented as separate rows in sections.csv with the primary
meeting flattened — so we operate on the top-level columns and ignore
the embedded meetings_json for simplicity.

Public API:
    sections_overlap(a, b)   →  bool
    find_conflicts(cand, stud) →  {section_id: [{course_id, ...}, ...]}
    summarize_for_card(...)  →  {status, summary, conflicting_count, total_sections}
"""
from __future__ import annotations

from typing import Iterable, Optional


# Ordered longest-first so the lexer prefers "Tu" over "T".
DAY_TOKENS: tuple[str, ...] = ("Tu", "Th", "Sa", "Su", "M", "W", "F")


def parse_days(s: str) -> set[str]:
    """
    Tokenize a UCI day-string into a set of canonical day codes.

    Examples:
        'TuTh'     → {'Tu', 'Th'}
        'MWF'      → {'M', 'W', 'F'}
        'MTuWThF'  → {'M', 'Tu', 'W', 'Th', 'F'}
        ''         → set()
    """
    if not s:
        return set()
    out: set[str] = set()
    i = 0
    while i < len(s):
        matched = False
        for tok in DAY_TOKENS:
            if s.startswith(tok, i):
                out.add(tok)
                i += len(tok)
                matched = True
                break
        if not matched:
            i += 1  # skip stray whitespace/junk
    return out


def time_to_minutes(t: str) -> Optional[int]:
    """
    Convert 'HH:MM' (24-hour) to minutes from midnight.

    Examples:
        '11:00' → 660
        '14:30' → 870
        ''      → None
        'TBA'   → None
    """
    if not t or ":" not in t:
        return None
    try:
        h, m = t.split(":", 1)
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _is_tba(sec: dict) -> bool:
    return str(sec.get("time_is_tba", "false")).lower() == "true"


def sections_overlap(a: dict, b: dict) -> bool:
    """
    True iff `a` and `b` share at least one meeting day AND their
    [start, end) clock intervals overlap.

    TBA sections (time_is_tba=true) and sections with unparseable times
    are treated as never conflicting — we'd rather miss a real conflict
    than falsely warn about a TBA placeholder.
    """
    if _is_tba(a) or _is_tba(b):
        return False

    days_shared = parse_days(a.get("days", "")) & parse_days(b.get("days", ""))
    if not days_shared:
        return False

    sa = time_to_minutes(a.get("start_time", ""))
    ea = time_to_minutes(a.get("end_time",   ""))
    sb = time_to_minutes(b.get("start_time", ""))
    eb = time_to_minutes(b.get("end_time",   ""))
    if None in (sa, ea, sb, eb):
        return False

    # Half-open interval test: [sa, ea) overlaps [sb, eb) iff sa < eb AND sb < ea.
    return sa < eb and sb < ea


def _format_meeting_window(sec: dict) -> str:
    """Human-readable: 'MWF 10:00–10:50'."""
    days = sec.get("days") or "TBA"
    s    = sec.get("start_time") or "?"
    e    = sec.get("end_time")   or "?"
    return f"{days} {s}\u2013{e}"   # \u2013 = en-dash


def find_conflicts(
    candidate_sections: Iterable[dict],
    student_sections:   Iterable[dict],
) -> dict[str, list[dict]]:
    """
    For each candidate section, list the student sections it conflicts with.

    Self-comparisons (same `section_id`) are skipped — this matters when a
    candidate course is somehow already on the student's schedule.

    Returns:
        {candidate_section_id: [
            {course_id, section_code, window},
            ...
        ]}
        Empty dict ⇔ no conflicts at all.
    """
    student_list = list(student_sections)
    out: dict[str, list[dict]] = {}
    for cand in candidate_sections:
        cand_id = cand.get("section_id", "")
        if not cand_id:
            continue
        confs: list[dict] = []
        for stud in student_list:
            if stud.get("section_id") == cand_id:
                continue
            if sections_overlap(cand, stud):
                confs.append({
                    "course_id":    stud.get("course_id", ""),
                    "section_code": stud.get("sectionCode", ""),
                    "window":       _format_meeting_window(stud),
                })
        if confs:
            out[cand_id] = confs
    return out


def summarize_for_card(
    candidate_sections: list[dict],
    section_conflicts:  dict[str, list[dict]],
) -> dict:
    """
    Roll per-section conflicts up to course-level for display.

    Three states:
      - "none"  no candidate section conflicts → card shows nothing
      - "some"  some sections conflict → yellow badge, students can pick another section
      - "all"   every section conflicts → red badge, real warning

    Returns:
        {
          status:             "none" | "some" | "all",
          summary:            human-readable string for the badge,
          conflicting_count:  int,
          total_sections:     int,
        }
    """
    total = len(candidate_sections)
    if total == 0:
        return {"status": "none", "summary": "", "conflicting_count": 0, "total_sections": 0}

    conflicting = [
        s for s in candidate_sections
        if section_conflicts.get(s.get("section_id", ""))
    ]
    n_conf = len(conflicting)

    if n_conf == 0:
        return {"status": "none", "summary": "", "conflicting_count": 0, "total_sections": total}

    if n_conf == total:
        # Every section conflicts — surface the first concrete conflict.
        first_conf_list = section_conflicts.get(conflicting[0].get("section_id", ""), [])
        if first_conf_list:
            f = first_conf_list[0]
            summary = f"Conflicts with {f['course_id']} ({f['window']})"
        else:
            summary = "All sections conflict with current schedule"
        return {"status": "all", "summary": summary, "conflicting_count": n_conf, "total_sections": total}

    # Mixed — student can still pick a non-conflicting section.
    summary = f"{n_conf} of {total} sections conflict with current schedule"
    return {"status": "some", "summary": summary, "conflicting_count": n_conf, "total_sections": total}