"""
Computer Science, B.S. — Major Requirements (2025-26 Edition).

Hand-encoded from raw scraper output + manual verification against
https://catalogue.uci.edu/donaldbrenschoolofinformationandcomputersciences/
departmentofcomputerscience/computerscience_bs/

Schema designed to support student-progress calculation:

    required_all      AND list — every course must be completed
    choice_groups     each group: pick one option (a list of course IDs)
    electives.scope_courses   universe of courses that count toward elective N
    electives.count   how many courses needed from that scope
    electives.sub_requirements   additional constraints (≥2 projects, etc.)
    specializations   pick one entry; complete its required + additional

All course IDs use the project's *colloquial* form (CS122A, ICS33, MATH2A),
not the catalogue's spaced form ('COMPSCI 122A'). The conversion follows
db.py's colloquial_course_id() rules.
"""
from __future__ import annotations


MAJOR = {
    "slug": "computerscience_bs",
    "name": "Computer Science",
    "degree": "B.S.",
    "school": "Donald Bren School of Information and Computer Sciences",
    "department": "Computer Science",
    "catalogue_year": "2025-26",
    "catalogue_url": (
        "https://catalogue.uci.edu/donaldbrenschoolofinformationandcomputersciences/"
        "departmentofcomputerscience/computerscience_bs/"
    ),

    # ── Lower-division ──────────────────────────────────────
    "lower_division": {
        # Section A: pick one intro programming series
        "choice_groups": [
            {
                "name": "Programming intro sequence",
                "options": [
                    ["ICS31", "ICS32", "ICS33"],          # standard track
                    ["ICSH32", "ICS33"],                  # accelerated honors
                ],
            },
            # Section B (partial): pick one linear algebra
            {
                "name": "Linear algebra",
                "options": [["ICS6N"], ["MATH3A"]],
            },
        ],
        # Section B: required core (no choice)
        "required_all": [
            "ICS45C", "ICS46", "ICS51", "ICS53",
            "IN4MATX43",
            "MATH2A", "MATH2B",
            "ICS6B", "ICS6D",
            "STATS67",
        ],
        # Section C: 2 GE-II courses with departmental exclusions
        "ge_constraints": [
            {
                "category": "GE-II",
                "min_count": 2,
                "excluded_departments": ["Engineering", "ICS", "Economics", "Math"],
                "notes": (
                    "Two GE category II courses required, but NOT from "
                    "Engineering / ICS / Economics / Math. University Studies "
                    "courses allowed with CS Vice Chair approval."
                ),
            },
        ],
    },

    # ── Upper-division ──────────────────────────────────────
    "upper_division": {
        # Section A: required core
        "required_all": ["CS161", "ICS139W"],

        # Section B: 11 upper-div CS electives
        "electives": {
            "count": 11,
            "scope_description": "COMPSCI 103-160, 162-189 (CS161 itself is core, not elective), plus listed IN4MATX",
            "scope_courses": [
                # COMPSCI 103–160 range (commonly offered)
                "CS103", "CS111", "CS112", "CS113", "CS114", "CS115", "CS116",
                "CS117", "CS118", "CS121", "CS122A", "CS122B", "CS122C", "CS122D",
                "CS125", "CS131", "CS132", "CS133", "CS134", "CS141",
                "CS142A", "CS142B", "CS143A", "CS143B", "CS145", "CS147",
                "CS151", "CS152", "CS154",
                # COMPSCI 162–189
                "CS162", "CS163", "CS164", "CS165", "CS166", "CS167", "CS169",
                "CS171", "CS172B", "CS172C", "CS175", "CS177", "CS178", "CS179",
                "CS180A", "CS180B", "CS184A", "CS184C", "CS189",
                # IN4MATX explicitly listed
                "IN4MATX113", "IN4MATX115", "IN4MATX117",
                "IN4MATX121", "IN4MATX122", "IN4MATX124",
                "IN4MATX131", "IN4MATX133", "IN4MATX134",
            ],
            "sub_requirements": [
                {
                    "name": "Project courses (≥2)",
                    "count": 2,
                    "scope": [
                        "CS113", "CS114", "CS117", "CS118",
                        "CS122B", "CS122C", "CS122D", "CS125",
                        "CS133", "CS142B", "CS143B", "CS145", "CS147",
                        "CS154", "CS165", "CS175",
                        "CS180A", "CS180B", "CS189",
                        "IN4MATX117", "IN4MATX134",
                    ],
                    "notes": [
                        "CS180A and CS180B together count as one project — "
                        "both must be completed for credit.",
                    ],
                },
                {
                    "name": "Specialization",
                    "ref": "specializations",
                    "notes": [
                        "Choose exactly one of the nine specializations below. "
                        "Cannot pursue more than one.",
                    ],
                },
            ],
        },
    },

    # ── 9 specializations ───────────────────────────────────
    # Within B-2 above. Each demands either a fixed set or N-from-list.
    "specializations": [
        {
            "name": "Algorithms",
            "type": "n_from_list",
            "count": 4,
            "scope": ["CS162", "CS163", "CS164", "CS165",
                      "CS166", "CS167", "CS169"],
        },
        {
            "name": "Architecture and Embedded Systems",
            "type": "n_from_list",
            "count": 4,
            "scope": ["CS145", "CS147", "CS151", "CS152", "CS154"],
        },
        {
            "name": "Bioinformatics",
            "type": "required_plus_n",
            "required": ["CS184A"],
            "additional_count": 2,
            "additional_scope": ["CS172B", "CS172C", "CS178", "CS184C", "CS189"],
        },
        {
            "name": "General Computer Science",
            "type": "n_from_list",
            "count": 11,
            "scope_description": "COMPSCI 103-189 except CS161",
            # The scope here equals upper-division.electives.scope_courses
            # minus CS161 — we don't duplicate; the calculator references
            # upper-division electives scope.
            "scope_ref": "upper_division.electives.scope_courses",
        },
        {
            "name": "Information",
            "type": "required_plus_n",
            "required": ["CS121", "CS122A", "CS178"],
            "additional_count": 4,
            "additional_scope": [
                "ICS45J", "CS122B", "CS122C", "CS122D", "CS125",
                "CS132", "CS134", "CS141", "CS142A", "CS143A",
                "CS163", "CS165", "CS167", "CS179",
            ],
            "additional_constraints": [
                {
                    "name": "Project-tier course (≥1)",
                    "min_count": 1,
                    "scope": ["CS122B", "CS122C", "CS122D", "CS125", "CS179"],
                },
            ],
        },
        {
            "name": "Intelligent Systems",
            "type": "required_plus_n",
            "required": ["CS171", "CS175", "CS178"],
            "additional_count": 3,
            "additional_scope": [
                "CS116", "CS121", "CS125",
                "CS162", "CS163", "CS164", "CS169",
                "CS177", "CS179",
            ],
        },
        {
            "name": "Networked Systems",
            "type": "required_all",
            "required": ["CS132", "CS133", "CS134", "CS143A"],
        },
        {
            "name": "Systems and Software",
            "type": "n_from_list",
            "count": 3,
            "scope": ["CS131", "CS141", "CS142A", "CS142B", "CS143A", "CS143B"],
        },
        {
            "name": "Visual Computing",
            "type": "n_from_list",
            "count": 4,
            "scope": ["CS111", "CS112", "CS114", "CS116", "CS117", "CS118"],
        },
    ],
}


def get() -> dict:
    """Return the CS B.S. requirements dict (single source of truth)."""
    return MAJOR


def all_required_anywhere() -> set[str]:
    """
    Return the union of every course that must be completed *at least once*
    (ignoring choice groups). Useful for a coarse "what's mentioned in the
    major spec at all" check — drives the validator's hallucination guard.

    Note: this is a superset; choice groups mean a student satisfies the
    major without taking some of these. For real progress logic, see
    `compute_progress` (TODO in a future module).
    """
    cids: set[str] = set()
    cids.update(MAJOR["lower_division"]["required_all"])
    cids.update(MAJOR["upper_division"]["required_all"])
    for grp in MAJOR["lower_division"]["choice_groups"]:
        for opt in grp["options"]:
            cids.update(opt)
    cids.update(MAJOR["upper_division"]["electives"]["scope_courses"])
    for spec in MAJOR["specializations"]:
        cids.update(spec.get("required", []))
        cids.update(spec.get("scope", []))
        cids.update(spec.get("additional_scope", []))
    return cids