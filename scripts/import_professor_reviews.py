"""
Import RateMyProfessor reviews into SQLite.

Source:      data/professor/uci_reviews.ndjson   (~83k lines, 67MB)
Destination: data/professor/professor_reviews.db

Run once after refreshing the ndjson:

    python scripts/import_professor_reviews.py

Re-running is safe — it drops and recreates the `reviews` table. Indexes
are built on (teacher_legacy_id) and (teacher_legacy_id, class_norm) so
the runtime query path is O(log n).

class_norm is the lowercase, whitespace-stripped course token from the
review (e.g. "51B" → "51b"). The professor JSON / sections.csv use the
same coarse course code form, so this is what we'll join on at query
time.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / "data" / "professor" / "uci_reviews.ndjson"
DST  = ROOT / "data" / "professor" / "professor_reviews.db"


SCHEMA = """
CREATE TABLE reviews (
    review_id            TEXT PRIMARY KEY,
    teacher_legacy_id    INTEGER NOT NULL,
    class_raw            TEXT,
    class_norm           TEXT,
    comment              TEXT,
    clarity_rating       REAL,
    difficulty_rating    REAL,
    helpful_rating       REAL,
    grade                TEXT,
    rating_tags          TEXT,
    would_take_again     INTEGER,
    is_for_credit        INTEGER,
    is_for_online_class  INTEGER,
    attendance_mandatory TEXT,
    textbook_use         INTEGER,
    thumbs_up            INTEGER,
    thumbs_down          INTEGER,
    created_at           TEXT
);
CREATE INDEX idx_reviews_legacy            ON reviews(teacher_legacy_id);
CREATE INDEX idx_reviews_legacy_class      ON reviews(teacher_legacy_id, class_norm);
"""


def _norm_class(s: str | None) -> str | None:
    if not s:
        return None
    return "".join(s.split()).lower() or None


def _to_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_bool_int(v) -> int | None:
    """RMP serializes bool flags as true/false/null/1/0. Normalize to 0/1/None."""
    if v is True or v == 1:
        return 1
    if v is False or v == 0:
        return 0
    return None


def main() -> int:
    if not SRC.exists():
        print(f"[error] source not found: {SRC}", file=sys.stderr)
        return 1

    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists():
        DST.unlink()

    conn = sqlite3.connect(DST)
    conn.executescript(SCHEMA)

    insert_sql = """
        INSERT OR REPLACE INTO reviews (
            review_id, teacher_legacy_id, class_raw, class_norm, comment,
            clarity_rating, difficulty_rating, helpful_rating, grade,
            rating_tags, would_take_again, is_for_credit, is_for_online_class,
            attendance_mandatory, textbook_use, thumbs_up, thumbs_down, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    t0 = time.time()
    rows: list[tuple] = []
    BATCH = 5000
    total = 0
    bad = 0

    with SRC.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue

            legacy = _to_int(r.get("teacher_legacy_id"))
            if legacy is None:
                bad += 1
                continue

            rows.append((
                r.get("id") or f"L{legacy}-{r.get('legacyId')}",
                legacy,
                r.get("class"),
                _norm_class(r.get("class")),
                r.get("comment"),
                r.get("clarityRating"),
                r.get("difficultyRating"),
                r.get("helpfulRating"),
                r.get("grade"),
                r.get("ratingTags"),
                _to_bool_int(r.get("wouldTakeAgain")),
                _to_bool_int(r.get("isForCredit")),
                _to_bool_int(r.get("isForOnlineClass")),
                r.get("attendanceMandatory"),
                _to_int(r.get("textbookUse")),
                _to_int(r.get("thumbsUpTotal")) or 0,
                _to_int(r.get("thumbsDownTotal")) or 0,
                r.get("date"),
            ))

            if len(rows) >= BATCH:
                conn.executemany(insert_sql, rows)
                total += len(rows)
                rows.clear()

    if rows:
        conn.executemany(insert_sql, rows)
        total += len(rows)

    conn.commit()
    conn.execute("ANALYZE")
    conn.close()

    dt = time.time() - t0
    size_mb = DST.stat().st_size / (1024 * 1024)
    print(f"[ok] {total:,} reviews → {DST}  ({size_mb:.1f} MB, {dt:.1f}s)")
    if bad:
        print(f"[warn] {bad} rows skipped (bad json or missing teacher_legacy_id)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
