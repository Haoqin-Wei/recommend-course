"""
Anteater API capability probe — what can we fetch for the onboarding flow?

P1-1a (Phase A) data-availability verification. Runs read-only GETs and
reports what's reachable so we can decide which pieces still need
scraping or hand-curation before building the onboarding wizard.

Usage:  python -m scripts.probe_anteater_api
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from urllib.request import urlopen, Request
from urllib.error import HTTPError

BASE = "https://anteaterapi.com/v2/rest"
TIMEOUT = 15
# Anteater's edge returns 403 to clients with no User-Agent
# (urllib's default "Python-urllib/x.y" trips a block). Any plain UA works.
UA = "uci-course-advisor/probe (+https://github.com/zotadvisor)"


def _get(path: str) -> dict:
    url = f"{BASE}{path}" if path.startswith("/") else f"{BASE}/{path}"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except HTTPError as e:
        return {"ok": False, "_http_code": e.code, "_url": url}


# ── Probe ────────────────────────────────────────────────

def probe_departments():
    d = _get("/websoc/departments")
    data = d.get("data", []) if d.get("ok") else []
    print(f"  departments:  {len(data):>4d} entries   keys: {list(data[0].keys()) if data else 'n/a'}")
    return data


def probe_majors():
    d = _get("/programs/majors")
    data = d.get("data", []) if d.get("ok") else []
    by_div = defaultdict(lambda: defaultdict(int))
    for m in data:
        by_div[m.get("division", "?")][m.get("type", "?")] += 1
    print(f"  majors:       {len(data):>4d} programs")
    for div in sorted(by_div):
        print(f"    └─ {div}: " + ", ".join(f"{t}={n}" for t, n in sorted(by_div[div].items())))
    return data


def probe_one_major(program_id: str, label: str):
    d = _get(f"/programs/major?programId={program_id}")
    data = d.get("data", {}) if d.get("ok") else {}
    reqs = data.get("requirements", [])

    def walk(r, depth=0):
        out_n_courses = 0
        out_n_slots = 0
        if r.get("requirementType") == "Course":
            out_n_courses += len(r.get("courses", []))
            out_n_slots += 1
        elif r.get("requirementType") == "Group":
            for sub in r.get("requirements", []):
                c, s = walk(sub, depth + 1)
                out_n_courses += c
                out_n_slots += s
        return out_n_courses, out_n_slots

    total_courses, total_slots = 0, 0
    for r in reqs:
        c, s = walk(r)
        total_courses += c
        total_slots += s
    spec = "specs=" + str(len(data.get("specializations") or []))
    print(f"  {label:<30s}  top-reqs={len(reqs):>2d}  total course-slots={total_slots:>3d}  unique-course-listings={total_courses:>4d}  ({spec})")
    return data


def probe_ge():
    out = {}
    for kind in ("GE", "UC", "CHC4", "CHC2"):
        d = _get(f"/programs/ugradRequirements?id={kind}")
        if not d.get("ok"):
            print(f"  {kind:<6s}: failed  ({d.get('message') or d.get('_http_code')})")
            continue
        data = d.get("data", {})
        reqs = data.get("requirements", [])
        # Count leaf course lists
        listings = 0
        unique_courses = set()
        def walk(r):
            nonlocal listings
            if r.get("requirementType") == "Course":
                listings += 1
                for c in r.get("courses", []):
                    unique_courses.add(c)
            elif r.get("requirementType") == "Group":
                for sub in r.get("requirements", []):
                    walk(sub)
        for r in reqs:
            walk(r)
        print(f"  {kind:<6s}: top-reqs={len(reqs):>2d}  leaf-listings={listings:>3d}  unique-courses={len(unique_courses):>4d}")
        out[kind] = data
    return out


def probe_specializations():
    d = _get("/programs/specializations")
    if not d.get("ok"):
        print(f"  specializations: failed")
        return []
    data = d.get("data", [])
    print(f"  specializations: {len(data)} entries")
    return data


# ── Main ─────────────────────────────────────────────────

def main():
    print("──────────────────────────────────────────────")
    print("  Anteater API probe — onboarding data sources")
    print("──────────────────────────────────────────────")

    # Quick liveness
    if not _get("/ping").get("ok"):
        print("WARN: /ping failed — API may be down. Continuing anyway.")

    print("\n[1] Catalogue scaffolding")
    print("─" * 50)
    depts  = probe_departments()
    majors = probe_majors()
    specs  = probe_specializations()

    print("\n[2] GE / external undergrad requirements")
    print("─" * 50)
    ge = probe_ge()

    print("\n[3] Sample major requirement trees")
    print("─" * 50)
    # Each of these returns a structured requirement tree we can render
    # as cards in the onboarding course-picker.
    samples = [
        ("BS-201", "Computer Science"),
        ("BS-19H", "Informatics"),
        ("BS-06G", "Software Engineering"),
        ("BS-0AM", "Data Science"),
        ("BS-459", "Information & CS (general)"),
        ("BS-193", "Computer Science & Engineering"),
        ("BS-01N", "Business Information Management"),
    ]
    for pid, label in samples:
        probe_one_major(pid, label)

    # Verdict
    print("\n──────────────────────────────────────────────")
    print("  Verdict")
    print("──────────────────────────────────────────────")
    api_has = []
    api_missing = []

    api_has.append(f"departments × {len(depts)} (deptCode + deptName)")
    api_has.append(f"majors × {len(majors)} (id, name, type, division, specs)")
    api_has.append(f"per-major requirement tree (label + courses[] per leaf)")
    if "GE" in ge:
        api_has.append(f"GE categories (full tree with course lists)")
    if any(k in ge for k in ("UC", "CHC4", "CHC2")):
        api_has.append("UC / honors / CHC requirements (same structure)")

    api_missing.append("department → college/school mapping (eg COMPSCI → Donald Bren ICS) — must hand-code (~50 lines)")
    api_missing.append("year-appropriateness per course (which is freshman-friendly) — use course level (1-99 lower / 100+ upper) as proxy")

    print("\n[✓] API reachable:")
    for x in api_has:
        print(f"    • {x}")
    print("\n[✗] Needs manual data:")
    for x in api_missing:
        print(f"    • {x}")

    print()


if __name__ == "__main__":
    sys.exit(main() or 0)
