"""
Fetch UCI course metadata from Anteater API.

Subcommands:
    courses    Fetch course catalog (title, units, description, prereq tree, ...)

Usage:
    # Set API key (recommended):
    export ANTEATER_API_KEY=ak_secret_xxxxx
    # or put it in .env next to this script

    # Smoke test with one course:
    python3 scripts/fetch_uci_data.py courses --id COMPSCI122A

    # Pull metadata for every course that appears in your sections.csv:
    python3 scripts/fetch_uci_data.py courses --from-sections

    # Single department (large but bounded):
    python3 scripts/fetch_uci_data.py courses --department COMPSCI

Outputs (in --out-dir, default data/uci/):
    courses.csv

CSV is merged by course_id — running multiple times is safe and idempotent.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Need requests. Run: python3 -m pip install requests", file=sys.stderr)
    sys.exit(1)


BASE_URL = "https://anteaterapi.com/v2/rest"


# ── Env loading ──────────────────────────────────────────

def _load_dotenv():
    """Minimal .env loader. Doesn't pull in python-dotenv as a dependency."""
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def _get_api_key():
    _load_dotenv()
    key = os.getenv("ANTEATER_API_KEY")
    if not key:
        print(
            "WARNING: ANTEATER_API_KEY not set. Using unauthenticated quota "
            "(may hit rate limits).", file=sys.stderr,
        )
    return key


# ── HTTP ─────────────────────────────────────────────────

def _request(path, params=None, api_key=None, retries=3):
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{BASE_URL}{path}"
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 404:
                return None  # caller decides if this is fatal
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
    """
    Convert our CSV form to Anteater API form.
    Examples:
        ('COMPSCI', '122A')    → 'COMPSCI122A'
        ('SOC SCI', '178C')    → 'SOCSCI178C'
        ('I&C SCI', '33')      → 'I&CSCI33'
        ('CRM/LAW', 'C214')    → 'CRM/LAWC214'
    """
    return f"{department.replace(' ', '')}{course_number}"


def to_csv_course_id(department: str, course_number: str) -> str:
    """
    Convert API's (department, courseNumber) to our CSV course_id.
    Examples:
        ('COMPSCI', '122A')    → 'COMPSCI_122A'
        ('SOC SCI', '178C')    → 'SOC_SCI_178C'
        ('I&C SCI', '33')      → 'I&C_SCI_33'
    """
    return f"{department.replace(' ', '_')}_{course_number}"


# ── Courses CSV writer ───────────────────────────────────

COURSES_COLUMNS = [
    "course_id",          # 'COMPSCI_122A'   ← join key, matches sections.csv
    "department",         # 'COMPSCI'
    "course_number",      # '122A'
    "course_numeric",     # 122
    "title",
    "min_units",
    "max_units",
    "description",
    "course_level",       # 'Upper Division (100-199)'
    "school",
    "department_name",
    "same_as",            # 'EECS 116' or ''
    "restriction",
    "prerequisite_text",                # human-readable
    "prerequisite_tree_json",           # full nested AND/OR with minGrade
    "prerequisites_flat_json",          # flat list [{id, dept, courseNumber}, ...]
    "dependencies_flat_json",           # courses that have THIS as prereq
    "terms_offered_json",               # ['2025 Spring', '2026 Spring', ...]
    "ge_list",                          # 'GE-2|GE-7'  (pipe-joined; usually empty)
    "ge_text",
    "instructors_shortened_json",       # ['CAREY, M.', 'SHEU, C.', ...] historical
]


def _course_to_row(c: dict) -> dict:
    # API may return null instead of empty list for some fields — coalesce.
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
    # Flatten all instructor shortenedNames into one set (historical roster)
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
        "prerequisite_tree_json": json.dumps(
            c.get("prerequisiteTree") or {}, ensure_ascii=False,
        ),
        "prerequisites_flat_json": json.dumps(prereqs_flat, ensure_ascii=False),
        "dependencies_flat_json": json.dumps(deps_flat, ensure_ascii=False),
        "terms_offered_json": json.dumps(c.get("terms") or [], ensure_ascii=False),
        "ge_list": "|".join(c.get("geList") or []),
        "ge_text": c.get("geText", "") or "",
        "instructors_shortened_json": json.dumps(
            sorted(set(instr_names)), ensure_ascii=False,
        ),
    }


def _merge_into_csv(out_path: Path, new_rows: list, key_col: str = "course_id"):
    """Merge new_rows into out_path, deduping by key_col. Returns (added, total)."""
    existing: dict[str, dict] = {}

    if out_path.exists():
        with out_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                existing[r[key_col]] = r

    added = 0
    for r in new_rows:
        if r[key_col] not in existing:
            added += 1
        existing[r[key_col]] = r

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COURSES_COLUMNS)
        writer.writeheader()
        for r in existing.values():
            writer.writerow(r)

    return added, len(existing)


# ── Fetch strategies ─────────────────────────────────────

def fetch_one(course_id_api: str, api_key: str) -> dict | None:
    """Fetch a single course by API id (no underscore)."""
    return _request(f"/courses/{course_id_api}", api_key=api_key)


def fetch_by_id(course_id_input: str, out_dir: str):
    """--id mode. Accepts either 'COMPSCI122A' (API form) or 'COMPSCI_122A' (CSV form)."""
    api_key = _get_api_key()
    api_id = course_id_input.replace("_", "")
    print(f"Fetching {api_id} ...")
    data = fetch_one(api_id, api_key)
    if data is None:
        print(f"  ❌ {api_id} not found", file=sys.stderr)
        sys.exit(1)
    row = _course_to_row(data)
    out_path = Path(out_dir) / "courses.csv"
    added, total = _merge_into_csv(out_path, [row])
    print(f"  ✅ wrote {row['course_id']} ({'new' if added else 'updated'}) → {out_path} (total: {total})")


def fetch_by_department(dept: str, out_dir: str, sleep: float):
    """
    --department mode. Calls /courses?department=X. Handles pagination.
    NOTE: response format for paginated /courses isn't documented in the
    migration page we read. If this fails, we fall back to listing all
    courses for the dept by trying common course-number patterns — not
    implemented yet. For now, try the obvious endpoint.
    """
    api_key = _get_api_key()
    rows = []
    cursor = None
    page = 0

    while True:
        params = {"department": dept, "take": 100}
        if cursor:
            params["cursor"] = cursor
        data = _request("/courses", params=params, api_key=api_key)

        # Response could be either a list, or {items: [...], nextCursor: ...}
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
        print(f"❌ No courses returned for department={dept!r}. Try --id instead.")
        sys.exit(1)

    out_path = Path(out_dir) / "courses.csv"
    added, total = _merge_into_csv(out_path, rows)
    print(f"\n✅ Fetched {len(rows)} courses for {dept}. {added} new / {total} total in {out_path}")


def fetch_from_sections(out_dir: str, sleep: float, limit: int | None):
    """
    --from-sections mode. Reads data/uci/sections.csv, extracts every unique
    (department, courseNumber) pair, fetches each one's metadata, merges into
    courses.csv.

    Idempotent: re-running only fetches NEW courses that aren't yet in
    courses.csv. So you can interrupt and resume.
    """
    api_key = _get_api_key()
    sections_csv = Path(out_dir) / "sections.csv"
    courses_csv = Path(out_dir) / "courses.csv"

    if not sections_csv.exists():
        print(f"❌ {sections_csv} not found. Run import_term_data.py first.")
        sys.exit(1)

    # Collect (department, courseNumber) pairs
    pairs: set[tuple[str, str]] = set()
    with sections_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = (row.get("department") or "").strip()
            n = (row.get("courseNumber") or "").strip()
            if d and n:
                pairs.add((d, n))

    print(f"Found {len(pairs)} unique (department, courseNumber) pairs in sections.csv")

    # Skip ones already in courses.csv (resume support)
    already_have: set[str] = set()
    if courses_csv.exists():
        with courses_csv.open("r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                already_have.add(r["course_id"])
        print(f"  {len(already_have)} already in courses.csv — will skip those")

    to_fetch = sorted(
        pairs,
        key=lambda p: to_csv_course_id(*p),
    )
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
            data = fetch_one(api_id, api_key)
            if data is None:
                print(f"  [{i:4d}/{len(to_fetch)}] {csv_id}  ❌ 404")
                failed.append((dept, num))
            else:
                rows.append(_course_to_row(data))
                print(f"  [{i:4d}/{len(to_fetch)}] {csv_id}  ✅ {data.get('title', '?')[:60]}")
        except Exception as e:
            print(f"  [{i:4d}/{len(to_fetch)}] {csv_id}  ❌ {e}")
            failed.append((dept, num))

        # Save progress every 50 courses so a Ctrl+C doesn't lose work
        if rows and i % 50 == 0:
            _merge_into_csv(courses_csv, rows)
            rows = []

        time.sleep(sleep)

    if rows:
        _merge_into_csv(courses_csv, rows)

    # Final stats
    with courses_csv.open("r", encoding="utf-8") as f:
        total = sum(1 for _ in csv.DictReader(f))
    print(f"\n✅ Done. {total} courses in {courses_csv}.")
    if failed:
        print(f"❌ {len(failed)} courses failed to fetch (404 or error):")
        for d, n in failed[:20]:
            print(f"    {to_csv_course_id(d, n)}")
        if len(failed) > 20:
            print(f"    ... and {len(failed) - 20} more")


# ── CLI ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch UCI data from Anteater API into data/uci/*.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("courses", help="Fetch course catalog metadata")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", dest="course_id",
                   help="Fetch one course by id (e.g. COMPSCI122A or COMPSCI_122A)")
    g.add_argument("--from-sections", action="store_true",
                   help="Fetch every course that appears in sections.csv")
    g.add_argument("--department", help="Fetch all courses in a department")
    p.add_argument("--out-dir", default="data/uci")
    p.add_argument("--sleep", type=float, default=0.1,
                   help="Sleep between requests in seconds (default 0.1)")
    p.add_argument("--limit", type=int, default=None,
                   help="(--from-sections only) cap on how many to fetch")

    args = parser.parse_args()

    if args.cmd == "courses":
        if args.course_id:
            fetch_by_id(args.course_id, args.out_dir)
        elif args.from_sections:
            fetch_from_sections(args.out_dir, args.sleep, args.limit)
        elif args.department:
            fetch_by_department(args.department, args.out_dir, args.sleep)


if __name__ == "__main__":
    main()