"""
Department → School/College mapping.

UCI's API gives us department codes but no parent-school field. The
onboarding wizard needs this to let users pick a school first, then
filter the major dropdown to that school's programs.

Schema is small, stable, and changes maybe once a decade when UCI
spins up a new school — so it's hand-coded rather than scraped.

Source: catalogue.uci.edu/schoolsandprograms/. Last verified
2026-05 against the official "Schools and Programs" page.

If a department isn't in the mapping below, the caller should treat
it as "school: Other / Unknown" and still let the user pick — we'd
rather degrade gracefully than block onboarding on a missing entry.
"""

from __future__ import annotations


# Canonical school list (display order = order shown in the wizard).
# The slug is what we store in profile.json so renames don't break
# downstream consumers; the display name is what the UI shows.
SCHOOLS: list[dict[str, str]] = [
    {"slug": "ics",         "name": "Donald Bren School of Information & Computer Sciences"},
    {"slug": "engineering", "name": "Henry Samueli School of Engineering"},
    {"slug": "physical",    "name": "School of Physical Sciences"},
    {"slug": "biological",  "name": "School of Biological Sciences"},
    {"slug": "social",      "name": "School of Social Sciences"},
    {"slug": "humanities",  "name": "School of Humanities"},
    {"slug": "arts",        "name": "Claire Trevor School of the Arts"},
    {"slug": "business",    "name": "Paul Merage School of Business"},
    {"slug": "education",   "name": "School of Education"},
    {"slug": "ecology",     "name": "School of Social Ecology"},
    {"slug": "health",      "name": "Susan & Henry Samueli College of Health Sciences"},
    {"slug": "interdisc",   "name": "Interdisciplinary Studies"},
]


# Department-code prefix → school slug. UCI dept codes use varied
# casing/spacing in different APIs; we match against the uppercased
# code so callers don't have to normalize.
DEPT_CODE_TO_SCHOOL: dict[str, str] = {
    # ── ICS ─────────────────────────────────────────────
    "COMPSCI": "ics", "I&C SCI": "ics", "IN4MATX": "ics", "STATS": "ics",

    # ── Engineering ─────────────────────────────────────
    "BME":    "engineering",
    "CBE":    "engineering",   # Chemical & Biomolecular Engineering
    "CBEMS":  "engineering",
    "CEE":    "engineering",   # Civil & Environmental
    "ECPS":   "engineering",   # Electrical & Computer Power Systems
    "EECS":   "engineering",
    "ENGRMAE": "engineering",
    "ENGRMSE": "engineering",
    "ENGRCEE": "engineering",
    "ENGR":   "engineering",
    "MSE":    "engineering",
    "MAE":    "engineering",

    # ── Physical Sciences ───────────────────────────────
    "CHEM":     "physical",
    "MATH":     "physical",
    "PHYSICS":  "physical",
    "PHY SCI":  "physical",
    "EARTHSS":  "physical",

    # ── Biological Sciences ─────────────────────────────
    "BIO SCI":  "biological",
    "DEV BIO":  "biological",
    "ECO EVO":  "biological",
    "MOL BIO":  "biological",
    "NEURBIO":  "biological",
    "BIOCHEM":  "biological",
    "BIOSCI":   "biological",   # legacy/alt code

    # ── Social Sciences ─────────────────────────────────
    "ANTHRO":   "social",
    "COGS":     "social",
    "ECON":     "social",
    "POL SCI":  "social",
    "PSY BEH":  "social",
    "PSYCH":    "social",
    "SOCIOL":   "social",
    "SOC SCI":  "social",
    "PUBLIC POLICY": "social",
    "INTL ST":  "social",
    "LSCI":     "social",   # Language Science
    "MGT":      "social",   # cross-listed with Merage in some programs

    # ── Humanities ──────────────────────────────────────
    "AFAM":      "humanities",
    "ARTHIS":    "humanities",
    "ASIANAM":   "humanities",
    "CHC/LAT":   "humanities",
    "CHINESE":   "humanities",
    "CLASSIC":   "humanities",
    "COM LIT":   "humanities",
    "EAS":       "humanities",   # East Asian Studies
    "ENGLISH":   "humanities",
    "EURO ST":   "humanities",
    "FILM&MD":   "humanities",
    "FRENCH":    "humanities",
    "GERMAN":    "humanities",
    "GLBLCLT":   "humanities",
    "GLBL ME":   "humanities",
    "GREEK":     "humanities",
    "HEBREW":    "humanities",
    "HISTORY":   "humanities",
    "HUMAN":     "humanities",
    "ITALIAN":   "humanities",
    "JAPANSE":   "humanities",
    "KOREAN":    "humanities",
    "LATIN":     "humanities",
    "LIT JRN":   "humanities",
    "PERSIAN":   "humanities",
    "PHILOS":    "humanities",
    "PORTUG":    "humanities",
    "RELSTD":    "humanities",
    "RUSSIAN":   "humanities",
    "SPANISH":   "humanities",
    "VIETMSE":   "humanities",
    "WOMN ST":   "humanities",
    "WRITING":   "humanities",

    # ── Arts ────────────────────────────────────────────
    "ART":      "arts",
    "DANCE":    "arts",
    "DRAMA":    "arts",
    "MUSIC":    "arts",
    "ARTS":     "arts",

    # ── Business (Merage) ───────────────────────────────
    "MGMT":     "business",
    "MGMT EP":  "business",
    "MGMT FE":  "business",
    "MGMT HC":  "business",
    "MGMT MBA": "business",
    "MGMT PHD": "business",
    "MPAC":     "business",

    # ── Education ───────────────────────────────────────
    "EDUC":     "education",

    # ── Social Ecology ──────────────────────────────────
    "CRM/LAW":  "ecology",
    "PSY SCI":  "ecology",
    "PP&D":     "ecology",
    "SOC ECOL": "ecology",
    "URBN PL":  "ecology",

    # ── Health ──────────────────────────────────────────
    "NURSING":  "health",
    "PHRMSCI":  "health",
    "PUBHLTH":  "health",

    # ── Interdisciplinary / unsupported codes default ──
    "AC ENG":   "interdisc",
    "AI SCI":   "interdisc",
    "CAMPUSWR": "interdisc",
    "FLM&MDA":  "interdisc",
    "FLM&MDS":  "interdisc",
    "GLBLST":   "interdisc",
    "MIC BIO":  "interdisc",   # cross-listed
    "PHYSIO":   "interdisc",
    "ROTC":     "interdisc",
    "UNI STU":  "interdisc",
    "UNV STU":  "interdisc",
}


def school_for_dept(dept_code: str) -> str:
    """Resolve a department code to a school slug. Falls back to 'interdisc'."""
    key = (dept_code or "").upper().strip()
    return DEPT_CODE_TO_SCHOOL.get(key, "interdisc")


def departments_by_school() -> dict[str, list[str]]:
    """Inverse view: school_slug → list of dept_codes assigned to it."""
    out: dict[str, list[str]] = {s["slug"]: [] for s in SCHOOLS}
    for dept_code, school in DEPT_CODE_TO_SCHOOL.items():
        out.setdefault(school, []).append(dept_code)
    for codes in out.values():
        codes.sort()
    return out


def school_by_slug(slug: str) -> dict | None:
    for s in SCHOOLS:
        if s["slug"] == slug:
            return s
    return None
