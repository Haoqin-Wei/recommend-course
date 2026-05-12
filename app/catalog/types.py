"""
Catalog Core Data Types

Defines the canonical, term-scoped data structures the rest of the catalog
and validation layers operate on. These types are loader-agnostic —
every data source eventually normalizes into CourseRef / CourseRecord /
SectionRecord.

Design invariants:
  - CourseRef equality and hashing depend only on (department, course_number)
    in their canonical (uppercase, original spaces preserved) form.
  - SectionRecord.section_id is the UCI registrar's composite key:
    "{year}_{quarter}_{section_code}".
  - Provenance is mandatory on every Record so the validation layer can
    cite source files / terms when flagging issues.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── Provenance ───────────────────────────────────────────

@dataclass(frozen=True)
class Provenance:
    """Where a piece of catalog data came from.

    source_term:  actual UCI term the underlying records describe
    target_term:  term the *user* is querying about (may differ if
                  we're using historical data as a proxy for an
                  upcoming term)
    loader:       short identifier for the loader that produced this
    source_file:  optional debug pointer (relative path or url)
    """
    source_term: str          # e.g. "2025_Spring"
    target_term: str          # e.g. "2025_Spring" or "2026_Spring"
    loader: str               # e.g. "uci_relational" / "mock_data"
    source_file: Optional[str] = None

    @property
    def is_historical_proxy(self) -> bool:
        return self.source_term != self.target_term


# ── Course identity ──────────────────────────────────────

@dataclass(frozen=True)
class CourseRef:
    """A term-agnostic course identifier.

    Examples:
        CourseRef("COMPSCI", "122B")
        CourseRef("SOC SCI", "178C")
        CourseRef("CRM/LAW", "C214")

    Canonical form:
        - department: original UCI dept string (spaces, slashes,
          ampersands preserved), UPPERCASED
        - course_number: original UCI course number, UPPERCASED
    """
    department: str
    course_number: str

    def __post_init__(self):
        # Defensive: callers may pass lowercase; canonicalize.
        if self.department != self.department.upper():
            object.__setattr__(self, "department", self.department.upper())
        if self.course_number != self.course_number.upper():
            object.__setattr__(self, "course_number", self.course_number.upper())

    def display(self) -> str:
        """Registrar-style display: 'COMPSCI 122B', 'SOC SCI 178C'."""
        return f"{self.department} {self.course_number}"

    def course_id(self) -> str:
        """Storage key matching the cleaned xlsx course_id column.

        Replaces spaces in dept with underscores. Use ONLY for join
        keys, never for parsing back.
        """
        return f"{self.department.replace(' ', '_')}_{self.course_number}"


# ── Course-level record ──────────────────────────────────

@dataclass(frozen=True)
class CourseRecord:
    """Aggregated, term-scoped info about one course.

    Fields without an authoritative data source are None — the validator
    must treat None as 'cannot verify' rather than 'definitely false'.
    """
    ref: CourseRef
    course_numeric: Optional[int] = None         # for upper/lower division filtering
    title: Optional[str] = None                  # from catalog API (not yet available)
    units: Optional[float] = None
    description: Optional[str] = None
    prerequisites: tuple[CourseRef, ...] = field(default_factory=tuple)
    major_requirements: tuple[str, ...] = field(default_factory=tuple)
    ge_categories: tuple[str, ...] = field(default_factory=tuple)
    provenance: Optional[Provenance] = None


# ── Section-level record ─────────────────────────────────

@dataclass(frozen=True)
class SectionRecord:
    """One section of one course in one term."""
    section_id: str                              # "2025_Spring_34070"
    course: CourseRef
    section_code: str                            # "34070"
    term_id: str                                 # "2025_Spring"
    instructors: tuple[str, ...] = field(default_factory=tuple)
    ge_categories: tuple[str, ...] = field(default_factory=tuple)
    # Time/location/seats deliberately omitted — not in current data feed.
    provenance: Optional[Provenance] = None
