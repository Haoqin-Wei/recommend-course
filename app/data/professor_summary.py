"""
LLM-driven structured summary of a professor's student reviews.

Why this module exists: phase 1 gave the agent raw reviews and tag
counts. Both are useful but the agent has to keep re-reading the same
raw comments every time it wants to characterize a professor. This
module condenses the reviews ONCE into a structured English summary
(strengths / weaknesses / best_for / avoid_if / workload / exam_style /
grading_style / teaching_style) and caches it on disk so subsequent
calls are free.

Cache layout:
    data/professor/summaries/<legacy_id>.json
    {
      "_all":  { "summary": {...}, "model": "...", "summarized_at": "...", "n_reviews": 20 },
      "51b":   { "summary": {...}, "model": "...", "summarized_at": "...", "n_reviews": 25 },
      ...
    }

Cache is permanent — delete files (or the directory) to force refresh.
Same pattern as data/grades_cache/.

Public API (all async):
    summarize_professor(legacy_id, course=None) -> dict
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.data import professors as profs

logger = logging.getLogger(__name__)

_ROOT      = Path(__file__).resolve().parent.parent.parent
CACHE_DIR  = _ROOT / "data" / "professor" / "summaries"

# Cap reviews fed to the LLM so prompt size + cost are predictable.
MAX_REVIEWS_PER_SUMMARY = 20
MAX_COMMENT_CHARS       = 500


SUMMARY_SYSTEM_PROMPT = """\
You are summarizing RateMyProfessor-style student reviews for a UCI \
course advisor. The reviews come from real UCI students and may \
contradict each other — your job is to find the consistent themes, \
not parrot any one review.

Return ONLY a JSON object with this exact shape (no markdown fences):

{
  "strengths":       [3-5 short bullets, each under 12 words],
  "weaknesses":      [3-5 short bullets, each under 12 words],
  "best_for":        "one sentence: what kind of student thrives in this class",
  "avoid_if":        "one sentence: what kind of student should look elsewhere",
  "workload":        "low" | "moderate" | "high" | "mixed",
  "exam_style":      "short phrase, e.g. 'test-heavy, no curve' or 'projects + light midterms'",
  "grading_style":   "short phrase, e.g. 'generous curve', 'strict, no curve', 'effort-based'",
  "teaching_style":  "short phrase, e.g. 'lecture-heavy, clear', 'flipped classroom', 'hands-on labs'",
  "confidence":      "low" | "medium" | "high"   // how clear the signal is
}

Rules:
- Output English only, even if some reviews are in other languages.
- Stay grounded: every claim must be supported by multiple reviews or \
the explicit tags the reviewer applied.
- If the reviews disagree strongly (e.g. half say 'easy', half say \
'hard'), say that in strengths/weaknesses ("polarizing — opinions split") \
and set confidence='low'.
- If there are very few reviews, set confidence='low' and keep bullets short.
- DO NOT include the professor's name, the course code, raw quotes, or \
the review count — those are added separately.
- DO NOT speculate beyond what reviews actually say.
"""


def _cache_path(legacy_id: int) -> Path:
    return CACHE_DIR / f"{legacy_id}.json"


def _course_key(course: str | None) -> str:
    return profs._course_token(course) or "_all"   # reuse the same tail-stripping logic


def _load_cache_file(legacy_id: int) -> dict:
    p = _cache_path(legacy_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("cache read failed for %s: %s", p, e)
        return {}


def _write_cache_file(legacy_id: int, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_path(legacy_id)
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("cache write failed for %s: %s", p, e)


def _build_user_content(
    instructor_name: str,
    course: str | None,
    reviews: list[dict],
    tags: list[dict],
) -> str:
    """Render reviews + tags into a single user message for the LLM."""
    lines: list[str] = []
    lines.append(f"Instructor: {instructor_name}")
    if course:
        lines.append(f"Course filter: {course}")
    lines.append(f"Number of reviews provided: {len(reviews)}")
    lines.append("")

    if tags:
        tag_str = ", ".join(f"{t['tag']} ({t['count']})" for t in tags[:10])
        lines.append(f"Aggregated tags students applied: {tag_str}")
        lines.append("")

    lines.append("Student reviews (most-upvoted first):")
    for i, r in enumerate(reviews, 1):
        comment = (r.get("comment") or "").replace("\n", " ").strip()
        if len(comment) > MAX_COMMENT_CHARS:
            comment = comment[:MAX_COMMENT_CHARS] + "…"
        meta_bits = []
        if r.get("class"):              meta_bits.append(f"class={r['class']}")
        if r.get("grade"):              meta_bits.append(f"grade={r['grade']}")
        if r.get("difficulty") is not None:  meta_bits.append(f"difficulty={r['difficulty']}/5")
        if r.get("clarity") is not None:     meta_bits.append(f"clarity={r['clarity']}/5")
        if r.get("helpful") is not None:     meta_bits.append(f"helpful={r['helpful']}/5")
        if r.get("would_take_again") is not None:
            meta_bits.append(f"would_take_again={'yes' if r['would_take_again'] else 'no'}")
        if r.get("tags"):               meta_bits.append("tags=[" + "; ".join(r["tags"]) + "]")
        meta = " | ".join(meta_bits)
        lines.append(f"[{i}] {meta}")
        if comment:
            lines.append(f"    {comment}")

    return "\n".join(lines)


async def _call_summarizer(user_content: str) -> Optional[dict]:
    """Single LLM round-trip with json_object response_format."""
    # Local import — keeps this module importable without LLM credentials.
    from app.llm import adapter

    if not adapter.LLM_ENABLED:
        logger.info("summarize: LLM disabled, skipping")
        return None

    try:
        raw = await adapter._call_llm(
            SUMMARY_SYSTEM_PROMPT, user_content, json_mode=True,
        )
    except Exception as e:
        logger.error("summarize: LLM call failed: %s", e)
        return None

    parsed = adapter._parse_json_response(raw or "")
    if not isinstance(parsed, dict):
        logger.warning("summarize: LLM returned non-JSON or empty")
        return None
    return parsed


async def summarize_professor(
    legacy_id: int,
    course: Optional[str] = None,
    *,
    force_refresh: bool = False,
) -> dict:
    """Return a structured summary for an instructor (optionally per-course).

    Cache-first: if (legacy_id, course-or-_all) is on disk we return it
    without calling the LLM. Otherwise we pull up to MAX_REVIEWS reviews
    and tags from the local DB, call the LLM, store the result, return.

    Shape of returned dict:
        {
          "found":      bool,
          "source":     "cache" | "llm" | "none",
          "legacy_id":  int,
          "course":     str | None,
          "n_reviews":  int,
          "model":      str | None,
          "summarized_at": str | None,
          "summary":    dict | None,
          "reason":     str | None        # only when found=false
        }
    """
    if not legacy_id:
        return {"found": False, "source": "none", "reason": "missing legacy_id"}

    course_key = _course_key(course)

    cache = _load_cache_file(legacy_id)
    if not force_refresh and course_key in cache and isinstance(cache[course_key], dict):
        entry = cache[course_key]
        if entry.get("summary"):
            return {
                "found":         True,
                "source":        "cache",
                "legacy_id":     legacy_id,
                "course":        course,
                "n_reviews":     entry.get("n_reviews"),
                "model":         entry.get("model"),
                "summarized_at": entry.get("summarized_at"),
                "summary":       entry["summary"],
            }

    reviews = profs.get_reviews(legacy_id, course=course, limit=MAX_REVIEWS_PER_SUMMARY)
    if not reviews:
        return {
            "found":  False,
            "source": "none",
            "reason": (
                "no reviews found"
                + (f" for course {course}" if course else "")
            ),
        }
    tags = profs.aggregate_tags(legacy_id, course=course, top_n=10)

    rec = profs._by_legacy_id.get(legacy_id) if profs._loaded else None
    if rec is None:
        profs._build_index()
        rec = profs._by_legacy_id.get(legacy_id)
    instructor_name = (
        f"{(rec or {}).get('firstName', '')} {(rec or {}).get('lastName', '')}".strip()
        or f"legacy_id={legacy_id}"
    )

    user_content = _build_user_content(instructor_name, course, reviews, tags)
    t0 = time.time()
    parsed = await _call_summarizer(user_content)
    dt = time.time() - t0

    if not parsed:
        return {
            "found":  False,
            "source": "none",
            "reason": "summarizer LLM unavailable or returned invalid JSON",
        }

    from app.llm import adapter
    entry = {
        "summary":       parsed,
        "n_reviews":     len(reviews),
        "model":         adapter.LLM_MODEL,
        "summarized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    cache[course_key] = entry
    _write_cache_file(legacy_id, cache)
    logger.info(
        "summarize: legacy=%d course=%s n=%d %.2fs → cached",
        legacy_id, course or "_all", len(reviews), dt,
    )

    return {
        "found":         True,
        "source":        "llm",
        "legacy_id":     legacy_id,
        "course":        course,
        "n_reviews":     entry["n_reviews"],
        "model":         entry["model"],
        "summarized_at": entry["summarized_at"],
        "summary":       parsed,
    }


# ── Synchronous bridge ─────────────────────────────────
# The agent loop's tool dispatch is sync; this lets sync callers run a
# summary too (e.g. CLI verification scripts). Don't call this from
# inside the running event loop — use the async form there.

def summarize_professor_sync(
    legacy_id: int,
    course: Optional[str] = None,
    *,
    force_refresh: bool = False,
) -> dict:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        raise RuntimeError(
            "summarize_professor_sync called from a running event loop; "
            "use the async form instead."
        )
    return asyncio.run(
        summarize_professor(legacy_id, course=course, force_refresh=force_refresh)
    )
