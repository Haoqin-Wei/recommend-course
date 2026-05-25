"""
Audit local RMP coverage against the live UCI sections feed.

Pulls every distinct instructor name out of data/uci/section_instructors.csv
and tries to resolve each one through app.data.professors.lookup_professor.

Outputs:
  - stdout: hit/miss totals, top-50 misses, breakdown by ambiguity vs. unknown
  - data/professor/_misses.txt: full miss list for later cleanup
  - data/professor/_hits_sample.txt: 20 random hits with their tier (sanity check)

Run anytime the local snapshot is refreshed:
    python scripts/verify_professor_data.py
"""

from __future__ import annotations

import csv
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data import professors as profs   # noqa: E402

SECTION_INSTRUCTORS = ROOT / "data" / "uci" / "section_instructors.csv"
MISS_OUT            = ROOT / "data" / "professor" / "_misses.txt"
HITS_SAMPLE_OUT     = ROOT / "data" / "professor" / "_hits_sample.txt"


def main() -> int:
    if not SECTION_INSTRUCTORS.exists():
        print(f"[error] not found: {SECTION_INSTRUCTORS}", file=sys.stderr)
        return 1

    # Build section_id → department from sections.csv so we can pass a
    # dept hint when resolving each instructor — mirrors how the live
    # agent will call the tool (with the course's dept code in hand).
    sections_csv = ROOT / "data" / "uci" / "sections.csv"
    sec_dept: dict[str, str] = {}
    if sections_csv.exists():
        with sections_csv.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sid  = row.get("section_id")
                dept = row.get("department")
                if sid and dept:
                    sec_dept[sid] = dept

    # (name, dept) → section count.
    name_dept_counts: Counter[tuple[str, str]] = Counter()
    with SECTION_INSTRUCTORS.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("instructor_name_raw") or "").strip()
            # The bulk export sometimes leaves "STAFF" placeholders — ignore.
            if not name or name.upper() == "STAFF":
                continue
            dept = sec_dept.get(row.get("section_id", ""), "")
            name_dept_counts[(name, dept)] += 1

    # Distinct-name view (collapsing over dept).
    name_counts: Counter[str] = Counter()
    for (name, _), n in name_dept_counts.items():
        name_counts[name] += n

    # Build a parallel section-count tally so we report hit rate two ways:
    #   - by distinct instructor name (does the JSON cover the catalog?)
    #   - by section-name appearance  (does it cover the sections students see?)
    distinct_total = len(name_counts)
    section_total  = sum(name_counts.values())

    # Per (name, dept) hits — what the LLM will actually achieve when
    # it knows the course's dept.
    sections_hit_with_dept    = 0
    sections_hit_without_dept = 0
    for (name, dept), count in name_dept_counts.items():
        if profs.lookup_professor(name, department=dept):
            sections_hit_with_dept += count
        if profs.lookup_professor(name):
            sections_hit_without_dept += count

    # Per-distinct-name hits — what the LLM achieves without dept hints.
    hits_distinct = 0
    hits_sections = 0
    misses: list[tuple[str, int]] = []
    hits:   list[tuple[str, dict]] = []
    for name, count in name_counts.items():
        rec = profs.lookup_professor(name)
        if rec:
            hits_distinct += 1
            hits_sections += count
            hits.append((name, rec))
        else:
            misses.append((name, count))
    misses.sort(key=lambda kv: -kv[1])

    pct_d  = 100 * hits_distinct          / distinct_total if distinct_total else 0
    pct_s  = 100 * hits_sections          / section_total  if section_total  else 0
    pct_sd = 100 * sections_hit_with_dept / section_total  if section_total  else 0

    print("=" * 60)
    print("Professor name match audit")
    print("=" * 60)
    print(f"Distinct instructor strings : {distinct_total:,}")
    print(f"  hits  : {hits_distinct:,}  ({pct_d:.1f}%)")
    print(f"  miss  : {len(misses):,}")
    print(f"Section appearances         : {section_total:,}")
    print(f"  hits, no dept hint   : {hits_sections:,}  ({pct_s:.1f}%)")
    print(f"  hits, WITH dept hint : {sections_hit_with_dept:,}  ({pct_sd:.1f}%)")
    print(f"  Δ from dept tiebreak : +{sections_hit_with_dept - sections_hit_without_dept:,} sections")
    print()
    print(f"Top 50 unmatched names (by section count):")
    for name, count in misses[:50]:
        print(f"  {count:>5}  {name}")

    MISS_OUT.write_text(
        "\n".join(f"{count}\t{name}" for name, count in misses) + "\n",
        encoding="utf-8",
    )
    print(f"\nFull miss list → {MISS_OUT}")

    if hits:
        sample = random.sample(hits, min(20, len(hits)))
        lines = []
        for name, rec in sample:
            profile = profs.build_profile(rec)
            lines.append(
                f"{name:30s} → {profile['name']:30s}  "
                f"avg={profile['avg_rating']}  n={profile['num_ratings']}  "
                f"tier={profile['tier']['tier']}"
            )
        HITS_SAMPLE_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"20-hit sanity sample → {HITS_SAMPLE_OUT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
