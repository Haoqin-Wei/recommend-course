"""
Decision detection (Phase 3.5).

Scans user messages for commitment language — "I'll take CS122A",
"我决定选 CS131", "drop CS134" — and returns a normalized list of
decision strings. The caller (chat.py) is responsible for writing
detected decisions to session.decisions via
`app.data.sessions.append_decision`.

Two reasons we do this with regex instead of an LLM call:
  1. Cost — every turn would need an extra LLM round-trip.
  2. Latency — regex is microseconds, LLM is hundreds of ms.

False positives have low cost (one extra line in the pinned-decisions
block of the prompt). False negatives are unavoidable with regex; we
can upgrade to LLM-based detection later if accuracy becomes a problem.

Patterns cover English and Chinese — the demo user mixes both.

Public API:
    detect_decisions(text) -> list[str]
"""
from __future__ import annotations

import re


# Course-ID pattern: e.g. CS161, ICS 33, CS 122A, WRITING39B, MATH3A
_COURSE_ID = r"([A-Z]{2,8}\s?\d+[A-Z]?)"

# Each entry: (compiled pattern, template — uses {0} for the captured group)
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ── English commitments ──────────────────────────────
    (re.compile(
        rf"\b(?:I'?ll|I will|I'?m going to|going to)\s+"
        rf"(?:take|enroll in|sign up for|register for)\s+{_COURSE_ID}",
        re.IGNORECASE,
     ),
     "Take {0}"),

    (re.compile(rf"\bgoing\s+with\s+{_COURSE_ID}", re.IGNORECASE),
     "Going with {0}"),

    (re.compile(
        rf"\b(?:drop|dropping|skip|skipping)\s+{_COURSE_ID}",
        re.IGNORECASE,
     ),
     "Drop {0}"),

    (re.compile(
        rf"\bdecided\s+(?:on|to\s+take|to\s+enroll\s+in)\s+{_COURSE_ID}",
        re.IGNORECASE,
     ),
     "Decided: {0}"),

    # ── Chinese commitments ──────────────────────────────
    (re.compile(
        rf"(?:我决定|我打算|我要|准备)\s*"
        rf"(?:选|修|上|报|学)\s*{_COURSE_ID}",
     ),
     "选 {0}"),

    (re.compile(
        rf"(?:就选|就上|就修|敲定|定下|定了)\s*{_COURSE_ID}",
     ),
     "选 {0}"),

    (re.compile(
        rf"(?:放弃|不选|不修|不上)\s*{_COURSE_ID}",
     ),
     "放弃 {0}"),

    # ── Specialization commitments ───────────────────────
    (re.compile(
        r"\b(?:specialization|track|specializing\s+in|major\s+track)"
        r"\s*[:=]?\s*([A-Z][a-zA-Z][a-zA-Z\s]{2,30}?)"
        r"(?=[.,\n!?]|\s+(?:and|or|with|specialization|track)|$)",
        re.IGNORECASE,
     ),
     "Specialization: {0}"),

    (re.compile(
        r"(?:方向|专业方向)\s*[:：=]?\s*([\u4e00-\u9fff]{2,12})"
        r"(?=[，。、,.\n]|方向|$)",
     ),
     "方向: {0}"),
]


def _normalize_course_id(s: str) -> str:
    """Strip whitespace; "CS 161" → "CS161"."""
    s = s.strip()
    if re.match(r"^[A-Z]{2,8}\s+\d", s):
        return re.sub(r"\s+", "", s)
    return s


def detect_decisions(text: str) -> list[str]:
    """
    Scan a piece of text (typically the user's latest message) for
    commitment language. Returns a list of unique decision strings.

    Dedupe is case-insensitive within this single call. Cross-call
    dedupe is handled by `sessions.append_decision`.
    """
    if not text or not isinstance(text, str):
        return []

    decisions: list[str] = []
    seen: set[str] = set()

    for pattern, template in _PATTERNS:
        for match in pattern.finditer(text):
            captured = match.group(1)
            if not captured:
                continue
            # Trim and normalize course-id spacing
            value = _normalize_course_id(captured.strip())
            if not value or len(value) > 60:
                continue
            decision = template.format(value)
            if decision.lower() not in seen:
                decisions.append(decision)
                seen.add(decision.lower())

    return decisions