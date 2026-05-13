"""
Fetch UCI data from Anteater API.

Subcommands:
    courses    Fetch course catalog metadata (title, prereq, etc.)
    websoc     Fetch sections for a given term (days, time, instructors, ...)

Usage:
    # Set API key (recommended):
    export ANTEATER_API_KEY=ak_secret_xxxxx
    # or put it in .env next to this script

    # ── courses ──
    # Smoke test with one course:
    python3 scripts/fetch_uci_data.py courses --id COMPSCI122A
    # Pull metadata for every course that appears in sections.csv:
    python3 scripts/fetch_uci_data.py courses --from-sections
    # Single department:
    python3 scripts/fetch_uci_data.py courses --department COMPSCI

    # ── websoc (Phase 2.2) ──
    # Smoke test one course in one term:
    python3 scripts/fetch_uci_data.py websoc --year 2025 --quarter Spring \\
                                              --department COMPSCI --course 132
    # All sections in one department for one term:
    python3 scripts/fetch_uci_data.py websoc --year 2025 --quarter Spring \\
                                              --department COMPSCI
    # All sections in a term (loops every dept from courses.csv):
    python3 scripts/fetch_uci_data.py websoc --year 2026 --quarter Spring \\
                                              --all-departments

Outputs (in --out-dir, default data/uci/):
    courses.csv               from `courses` subcommand
    sections.csv              from `websoc` subcommand (extends, by section_id)
    section_instructors.csv   from `websoc` subcommand
    section_ge.csv            auto-regenerated from sections.csv ⋈ courses.csv

CSVs merge by primary key — running multiple times is safe and idempotent.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("Need requests. Run: python3 -m pip install requests", file=sys.stderr)
    sys.exit(1)


BASE_URL = "https://anteaterapi.com/v2/rest"

# Allowed values for --quarter (matches Anteater API).
VALID_QUARTERS = ("Fall", "Winter", "Spring", "Summer1", "Summer10wk", "Summer2")


# ── Env loading ──────────────────────────────────────────

def _load_dotenv():
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get_api_key() -> Optional[str]:
    _load_dotenv()
    key = os.getenv("ANTEATER_API_KEY")
    if not key:
        print("WARNING: ANTEATER_API_KEY not set. Using unauthenticated quota.",
              file=sys.stderr)
    return key


# ── HTTP ─────────────────────────────────────────────────

def _request(path: str, params: Optional[dict] = None,
             api_key: Optional[str] = None, retries: int = 3):
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{BASE_URL}{path}"
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "60"))
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"API error: {data.get('message')}")
            return data["data"]
        except (requests.RequestException, ValueError) as e:
            last_err = e
            if attempt == retries - 1:
                break
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Request failed after {retries} attempts: {last_err}")


# ── ID conversion ────────────────────────────────────────

def csv_to_api_id(department: str, course_number: str) -> str:
    """('COMPSCI', '122A') → 'COMPSCI122A' (API path style)."""
    return f"{department.replace(' ', '')}{course_number}"


def to_csv_course_id(department: str, course_number: str) -> str:
    """('COMPSCI', '122A') → 'COMPSCI_122A' (our canonical CSV style)."""
    return f"{department.replace(' ', '_')}_{course_number}"


# ── Generic CSV merge ────────────────────────────────────

def _merge_into_csv(out_path: Path, new_rows: list, columns: list, key_cols):
    """
    Merge new_rows into out_path CSV, deduping by key_cols.
    key_cols can be a single string or a tuple/list of strings.
    Returns (added, total).
    """
    if isinstance(key_cols, str):
        key_cols = (key_cols,)

    existing: dict[tuple, dict] = {}
    if out_path.exists():
        with out_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            old_header = reader.fieldnames or []
            if old_header and set(old_header) != set(columns):
                print(
                    f"  ⚠️  Header migrating in {out_path.name}: "
                    f"{len(old_header)} → {len(columns)} cols. "
                    f"Old rows padded with empty values for new columns."
                )
            for r in reader:
                normalized = {c: r.get(c, "") for c in columns}
                key = tuple(normalized.get(k, "") for k in key_cols)
                existing[key] = normalized

    added = 0
    for r in new_rows:
        normalized = {c: r.get(c, "") for c in columns}
        key = tuple(normalized.get(k, "") for k in key_cols)
        if key not in existing:
            added += 1
        existing[key] = normalized

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in existing.values():
            writer.writerow(r)

    return added, len(existing)


# ══════════════════════════════════════════════════════════
#  COURSES subcommand
# ══════════════════════════════════════════════════════════

COURSES_COLUMNS = [
    "course_id", "department", "course_number", "course_numeric",
    "title", "min_units", "max_units", "description",
    "course_level", "school", "department_name",
    "same_as", "restriction",
    "prerequisite_text", "prerequisite_tree_json",
    "prerequisites_flat_json", "dependencies_flat_json",
    "terms_offered_json", "ge_list", "ge_text",
    "instructors_shortened_json",
]


def _course_to_row(c: dict) -> dict:
    prereqs_flat = [
        {
            "id": to_csv_course_id(p["department"], p["courseNumber"]),
            "department": p["department"],
            "course_number": p["courseNumber"],
            "title": p.get("title", ""),
        }
        for p in (c.get("prerequisites") or [])
    ]
    deps_flat = [
        {
            "id": to_csv_course_id(d["department"], d["courseNumber"]),
            "department": d["department"],
            "course_number": d["courseNumber"],
            "title": d.get("title", ""),
        }
        for d in (c.get("dependencies") or [])
    ]
    instr_names = []
    for inst in (c.get("instructors") or []):
        instr_names.extend(inst.get("shortenedNames") or [])

    return {
        "course_id": to_csv_course_id(c["department"], c["courseNumber"]),
        "department": c["department"],
        "course_number": c["courseNumber"],
        "course_numeric": c.get("courseNumeric", ""),
        "title": c.get("title", ""),
        "min_units": c.get("minUnits", ""),
        "max_units": c.get("maxUnits", ""),
        "description": c.get("description", ""),
        "course_level": c.get("courseLevel", ""),
        "school": c.get("school", ""),
        "department_name": c.get("departmentName", ""),
        "same_as": c.get("sameAs", "") or "",
        "restriction": c.get("restriction", "") or "",
        "prerequisite_text": c.get("prerequisiteText", "") or "",
        "prerequisite_tree_json": json.dumps(c.get("prerequisiteTree") or {}, ensure_ascii=False),
        "prerequisites_flat_json": json.dumps(prereqs_flat, ensure_ascii=False),
        "dependencies_flat_json": json.dumps(deps_flat, ensure_ascii=False),
        "terms_offered_json": json.dumps(c.get("terms") or [], ensure_ascii=False),
        "ge_list": "|".join(c.get("geList") or []),
        "ge_text": c.get("geText", "") or "",
        "instructors_shortened_json": json.dumps(sorted(set(instr_names)), ensure_ascii=False),
    }


def fetch_one_course(api_id: str, api_key: Optional[str]) -> Optional[dict]:
    return _request(f"/courses/{api_id}", api_key=api_key)


def fetch_by_id(course_id_input: str, out_dir: str):
    api_key = _get_api_key()
    api_id = course_id_input.replace("_", "")
    print(f"Fetching {api_id} ...")
    data = fetch_one_course(api_id, api_key)
    if data is None:
        print(f"  ❌ {api_id} not found", file=sys.stderr)
        sys.exit(1)
    row = _course_to_row(data)
    out_path = Path(out_dir) / "courses.csv"
    added, total = _merge_into_csv(out_path, [row], COURSES_COLUMNS, "course_id")
    print(f"  ✅ wrote {row['course_id']} ({'new' if added else 'updated'}) → "
          f"{out_path} (total: {total})")


def fetch_courses_by_department(dept: str, out_dir: str, sleep: float):
    api_key = _get_api_key()
    rows: list[dict] = []
    cursor = None
    page = 0
    while True:
        params = {"department": dept, "take": 100}
        if cursor:
            params["cursor"] = cursor
        data = _request("/courses", params=params, api_key=api_key)
        if data is None:
            break
        if isinstance(data, list):
            items = data
            cursor = None
        else:
            items = data.get("items") or []
            cursor = data.get("nextCursor")
        for c in items:
            rows.append(_course_to_row(c))
        page += 1
        print(f"  page {page}: +{len(items)} (total so far: {len(rows)})")
        if not cursor or not items:
            break
        time.sleep(sleep)

    if not rows:
        print(f"❌ No courses returned for department={dept!r}.")
        sys.exit(1)

    out_path = Path(out_dir) / "courses.csv"
    added, total = _merge_into_csv(out_path, rows, COURSES_COLUMNS, "course_id")
    print(f"\n✅ Fetched {len(rows)} courses for {dept}. "
          f"{added} new / {total} total in {out_path}")


def fetch_courses_from_sections(out_dir: str, sleep: float, limit: Optional[int]):
    api_key = _get_api_key()
    sections_csv = Path(out_dir) / "sections.csv"
    courses_csv = Path(out_dir) / "courses.csv"

    if not sections_csv.exists():
        print(f"❌ {sections_csv} not found. Run `websoc` subcommand first, "
              f"or import_term_data.py.")
        sys.exit(1)

    pairs: set[tuple[str, str]] = set()
    with sections_csv.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = (row.get("department") or "").strip()
            n = (row.get("courseNumber") or "").strip()
            if d and n:
                pairs.add((d, n))
    print(f"Found {len(pairs)} unique (department, courseNumber) pairs in sections.csv")

    already_have: set[str] = set()
    if courses_csv.exists():
        with courses_csv.open("r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                already_have.add(r["course_id"])
        print(f"  {len(already_have)} already in courses.csv — will skip those")

    to_fetch = sorted(pairs, key=lambda p: to_csv_course_id(*p))
    to_fetch = [p for p in to_fetch if to_csv_course_id(*p) not in already_have]
    if limit:
        to_fetch = to_fetch[:limit]
    print(f"  Fetching {len(to_fetch)} new courses...\n")

    rows: list[dict] = []
    failed: list[tuple[str, str]] = []
    for i, (dept, num) in enumerate(to_fetch, 1):
        api_id = csv_to_api_id(dept, num)
        csv_id = to_csv_course_id(dept, num)
        try:
            data = fetch_one_course(api_id, api_key)
            if data is None:
                print(f"  [{i:4d}/{len(to_fetch)}] {csv_id}  ❌ 404")
                failed.append((dept, num))
            else:
                rows.append(_course_to_row(data))
                print(f"  [{i:4d}/{len(to_fetch)}] {csv_id}  ✅ "
                      f"{data.get('title', '?')[:60]}")
        except Exception as e:
            print(f"  [{i:4d}/{len(to_fetch)}] {csv_id}  ❌ {e}")
            failed.append((dept, num))
        if rows and i % 50 == 0:
            _merge_into_csv(courses_csv, rows, COURSES_COLUMNS, "course_id")
            rows = []
        time.sleep(sleep)

    if rows:
        _merge_into_csv(courses_csv, rows, COURSES_COLUMNS, "course_id")

    with courses_csv.open("r", encoding="utf-8") as f:
        total = sum(1 for _ in csv.DictReader(f))
    print(f"\n✅ Done. {total} courses in {courses_csv}.")
    if failed:
        print(f"❌ {len(failed)} courses failed (404 or error):")
        for d, n in failed[:20]:
            print(f"    {to_csv_course_id(d, n)}")
        if len(failed) > 20:
            print(f"    ... and {len(failed) - 20} more")


# ══════════════════════════════════════════════════════════
#  WEBSOC subcommand   (Phase 2.2)
# ══════════════════════════════════════════════════════════

SECTIONS_COLUMNS = [
    # ── Identity ──
    "section_id", "term_id", "course_id",
    "year", "quarter", "sectionCode",
    "department", "courseNumber", "courseNumeric",
    # ── Section metadata ──
    "sectionNum", "sectionType", "units", "status",
    "restrictions",
    # ── Time / location (from first meeting; full set in meetings_json) ──
    "days", "start_time", "end_time", "location", "time_is_tba",
    # ── Enrollment ──
    "max_capacity", "total_enrolled", "section_enrolled",
    "num_on_waitlist", "num_requested",
    # ── State ──
    "is_cancelled", "final_exam_json", "meetings_json",
    "updated_at",
]

SECTION_INSTRUCTORS_COLUMNS = ["section_id", "instructor_name_raw"]
SECTION_GE_COLUMNS = ["section_id", "ge_code"]


def _format_time(t: Optional[dict]) -> str:
    """{hour: 14, minute: 30} → '14:30'."""
    if not t:
        return ""
    h, m = t.get("hour"), t.get("minute")
    if h is None or m is None:
        return ""
    return f"{int(h):02d}:{int(m):02d}"


def _format_location(bldg) -> str:
    """['HIB 100'] → 'HIB 100'. Multi-building joined with ' / '."""
    if not bldg:
        return ""
    if isinstance(bldg, list):
        return " / ".join(str(b) for b in bldg if b)
    return str(bldg)


def _course_number_to_numeric(course_number: str) -> int:
    """'122A' → 122. 'H101C' → 101. '9B' → 9."""
    digits = "".join(c for c in course_number if c.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _websoc_section_to_rows(
    sec: dict, course: dict, dept: dict,
    year: int, quarter: str,
) -> tuple[dict, list[dict]]:
    """Convert one websoc section into (sections_row, [section_instructor_rows])."""
    section_code = sec.get("sectionCode", "")
    department = dept.get("deptCode", "")
    course_number = course.get("courseNumber", "")

    section_id = f"{year}_{quarter}_{section_code}"
    term_id = f"{year}_{quarter}"
    course_id_csv = to_csv_course_id(department, course_number)

    meetings = sec.get("meetings") or []
    first = meetings[0] if meetings else {}

    enrolled = sec.get("numCurrentlyEnrolled") or {}

    sections_row = {
        "section_id": section_id,
        "term_id": term_id,
        "course_id": course_id_csv,
        "year": str(year),
        "quarter": quarter,
        "sectionCode": section_code,
        "department": department,
        "courseNumber": course_number,
        "courseNumeric": str(_course_number_to_numeric(course_number)),
        "sectionNum": sec.get("sectionNum", "") or "",
        "sectionType": sec.get("sectionType", "") or "",
        "units": sec.get("units", "") or "",
        "status": sec.get("status", "") or "",
        "restrictions": sec.get("restrictions", "") or "",
        "days": first.get("days", "") or "",
        "start_time": _format_time(first.get("startTime")),
        "end_time": _format_time(first.get("endTime")),
        "location": _format_location(first.get("bldg")),
        "time_is_tba": str(bool(first.get("timeIsTBA"))).lower(),
        "max_capacity": sec.get("maxCapacity", "") or "",
        "total_enrolled": str(enrolled.get("totalEnrolled", "") or ""),
        "section_enrolled": str(enrolled.get("sectionEnrolled", "") or ""),
        "num_on_waitlist": sec.get("numOnWaitlist", "") or "",
        "num_requested": sec.get("numRequested", "") or "",
        "is_cancelled": str(bool(sec.get("isCancelled"))).lower(),
        "final_exam_json": json.dumps(sec.get("finalExam") or {}, ensure_ascii=False),
        "meetings_json": json.dumps(meetings, ensure_ascii=False),
        "updated_at": sec.get("updatedAt", "") or "",
    }

    instructor_rows = []
    for name in (sec.get("instructors") or []):
        name = (name or "").strip()
        if not name or name.upper() == "STAFF":
            # Skip the placeholder; otherwise validation would silently
            # accept "Professor Staff" as a known instructor.
            continue
        instructor_rows.append({
            "section_id": section_id,
            "instructor_name_raw": name,
        })

    return sections_row, instructor_rows


def _discover_departments_from_csv(out_dir: str) -> list[str]:
    """Read unique dept codes from courses.csv."""
    path = Path(out_dir) / "courses.csv"
    if not path.exists():
        print(f"❌ {path} not found. Run `fetch_uci_data.py courses --from-sections` first.")
        sys.exit(1)
    depts: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = (r.get("department") or "").strip()
            if d:
                depts.add(d)
    return sorted(depts)


def _regenerate_section_ge(out_dir: str) -> None:
    """
    Rebuild section_ge.csv by joining sections.csv ⋈ courses.csv.
    Each section inherits its course's ge_list; one row per (section, ge_code).
    websoc itself doesn't return GE info — only /courses does.
    """
    out_dir = Path(out_dir)
    sections_path = out_dir / "sections.csv"
    courses_path = out_dir / "courses.csv"
    ge_path = out_dir / "section_ge.csv"

    if not courses_path.exists():
        print(f"  ⚠️  Skipping section_ge: {courses_path} not found "
              f"(run `courses` first)")
        return
    if not sections_path.exists():
        return

    course_ge: dict[str, list[str]] = {}
    with courses_path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = r.get("course_id", "")
            codes = [g for g in (r.get("ge_list") or "").split("|") if g]
            if cid and codes:
                course_ge[cid] = codes

    rows: list[dict] = []
    with sections_path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r.get("section_id", "")
            cid = r.get("course_id", "")
            for code in course_ge.get(cid, []):
                rows.append({"section_id": sid, "ge_code": code})

    ge_path.parent.mkdir(parents=True, exist_ok=True)
    with ge_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SECTION_GE_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"  section_ge.csv: {len(rows)} rows regenerated")


def fetch_websoc(
    year: int, quarter: str,
    department: Optional[str] = None,
    course_number: Optional[str] = None,
    all_departments: bool = False,
    out_dir: str = "data/uci",
    sleep: float = 0.1,
):
    """
    Fetch /websoc for given (year, quarter, [department], [course]) and write to:
      sections.csv               (merge, key=section_id)
      section_instructors.csv    (merge, key=(section_id, instructor_name_raw))
      section_ge.csv             (regenerated from sections ⋈ courses)
    """
    api_key = _get_api_key()

    # Resolve department list
    if all_departments:
        depts = _discover_departments_from_csv(out_dir)
        print(f"Will fetch {len(depts)} departments for {year} {quarter}")
    elif department:
        depts = [department.strip()]
    else:
        raise ValueError("Must specify --department X or --all-departments")

    all_section_rows: list[dict] = []
    all_instructor_rows: list[dict] = []
    section_total = 0
    err_total = 0

    for i, dept in enumerate(depts, 1):
        params = {"year": str(year), "quarter": quarter, "department": dept}
        if course_number:
            params["courseNumber"] = course_number

        try:
            data = _request("/websoc", params=params, api_key=api_key)
        except Exception as e:
            print(f"  [{i:3d}/{len(depts)}] {dept:18s}  ❌ {e}")
            err_total += 1
            continue

        if not data:
            print(f"  [{i:3d}/{len(depts)}] {dept:18s}  (no data)")
            continue

        dept_section_count = 0
        for school in (data.get("schools") or []):
            for dept_block in (school.get("departments") or []):
                for course_block in (dept_block.get("courses") or []):
                    for sec in (course_block.get("sections") or []):
                        try:
                            sec_row, inst_rows = _websoc_section_to_rows(
                                sec, course_block, dept_block, year, quarter,
                            )
                            all_section_rows.append(sec_row)
                            all_instructor_rows.extend(inst_rows)
                            dept_section_count += 1
                        except Exception as e:
                            print(f"      parse error in "
                                  f"{dept}/{course_block.get('courseNumber')}: {e}")

        section_total += dept_section_count
        print(f"  [{i:3d}/{len(depts)}] {dept:18s}  → {dept_section_count} sections")
        time.sleep(sleep)

    # ── Write sections.csv ──
    print()
    sections_path = Path(out_dir) / "sections.csv"
    added, total = _merge_into_csv(
        sections_path, all_section_rows, SECTIONS_COLUMNS, "section_id",
    )
    print(f"sections.csv:            {len(all_section_rows)} fetched, "
          f"{added} new, {total} total")

    # ── Write section_instructors.csv ──
    inst_path = Path(out_dir) / "section_instructors.csv"
    added_i, total_i = _merge_into_csv(
        inst_path, all_instructor_rows,
        SECTION_INSTRUCTORS_COLUMNS,
        ("section_id", "instructor_name_raw"),
    )
    print(f"section_instructors.csv: {len(all_instructor_rows)} fetched, "
          f"{added_i} new, {total_i} total")

    # ── Regenerate section_ge.csv ──
    _regenerate_section_ge(out_dir)

    print(f"\n✅ Done. Fetched {section_total} sections from {len(depts)} departments.")
    if err_total:
        print(f"  ⚠️  {err_total} departments failed (see errors above)")


# ══════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Fetch UCI data from Anteater API into data/uci/*.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── courses ──
    pc = sub.add_parser("courses", help="Fetch course catalog metadata")
    g = pc.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", dest="course_id",
                   help="Fetch one course by id (e.g. COMPSCI122A or COMPSCI_122A)")
    g.add_argument("--from-sections", action="store_true",
                   help="Fetch every course that appears in sections.csv")
    g.add_argument("--department", help="Fetch all courses in a department")
    pc.add_argument("--out-dir", default="data/uci")
    pc.add_argument("--sleep", type=float, default=0.1)
    pc.add_argument("--limit", type=int, default=None,
                    help="(--from-sections only) cap on how many to fetch")

    # ── websoc ──
    pw = sub.add_parser("websoc", help="Fetch term-specific sections from WebSoc")
    pw.add_argument("--year", type=int, required=True, help="e.g. 2025")
    pw.add_argument("--quarter", required=True, choices=VALID_QUARTERS,
                    help="One of: " + ", ".join(VALID_QUARTERS))
    g2 = pw.add_mutually_exclusive_group(required=True)
    g2.add_argument("--department",
                    help='Single department (e.g. COMPSCI, "I&C SCI")')
    g2.add_argument("--all-departments", action="store_true",
                    help="Loop through every department in courses.csv")
    pw.add_argument("--course", dest="course_number",
                    help="Filter to one course number (use with --department for smoke test)")
    pw.add_argument("--out-dir", default="data/uci")
    pw.add_argument("--sleep", type=float, default=0.1)

    args = parser.parse_args()

    if args.cmd == "courses":
        if args.course_id:
            fetch_by_id(args.course_id, args.out_dir)
        elif args.from_sections:
            fetch_courses_from_sections(args.out_dir, args.sleep, args.limit)
        elif args.department:
            fetch_courses_by_department(args.department, args.out_dir, args.sleep)

    elif args.cmd == "websoc":
        fetch_websoc(
            year=args.year, quarter=args.quarter,
            department=args.department,
            course_number=args.course_number,
            all_departments=args.all_departments,
            out_dir=args.out_dir,
            sleep=args.sleep,
        )


if __name__ == "__main__":
    main()