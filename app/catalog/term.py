"""
Term — quarter+year canonical type, parsing, and ordering.

UCI quarters in academic order: Fall → Winter → Spring → Summer.
We treat "term_id" strings of the form "{YEAR}_{Quarter}" as the
canonical storage form (matches the xlsx term_id column).

TermRegistry is a process-wide store of which terms have data
available. The CatalogCache populates it as loaders register.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import re


_QUARTER_ORDER = {"Fall": 0, "Winter": 1, "Spring": 2, "Summer": 3}


@dataclass(frozen=True, order=False)
class Term:
    year: int
    quarter: str                                 # "Fall" | "Winter" | "Spring" | "Summer"

    def __post_init__(self):
        if self.quarter not in _QUARTER_ORDER:
            raise ValueError(f"Unknown quarter: {self.quarter!r}")

    @property
    def term_id(self) -> str:
        """Canonical storage form, matches xlsx term_id column."""
        return f"{self.year}_{self.quarter}"

    def display(self) -> str:
        return f"{self.quarter} {self.year}"

    def __lt__(self, other: "Term") -> bool:
        # Academic-order comparison: later year = greater; within year,
        # Summer > Spring > Winter > Fall in time-order.
        # _QUARTER_ORDER ranks Fall=0..Summer=3, which IS calendar order
        # within an academic year (Fall starts the year). So a higher
        # value = later in time within the year.
        return (self.year, _QUARTER_ORDER[self.quarter]) < (
            other.year, _QUARTER_ORDER[other.quarter]
        )

    @classmethod
    def parse(cls, s: str) -> Optional["Term"]:
        """Accept 'Fall 2025', '2025_Fall', 'Spring2025', etc.

        Returns None on unparseable input — never raises.
        """
        if not s:
            return None
        s = s.strip()
        # Year-first: "2025 Spring" / "2025_Spring" / "2025Spring"
        m = re.fullmatch(
            r"(\d{4})[_ ]?(Fall|Winter|Spring|Summer)", s, re.IGNORECASE,
        )
        if m:
            return cls(year=int(m.group(1)), quarter=m.group(2).capitalize())
        # Quarter-first: "Spring 2025" / "Spring_2025" / "Spring2025"
        m = re.fullmatch(
            r"(Fall|Winter|Spring|Summer)[_ ]?(\d{4})", s, re.IGNORECASE,
        )
        if m:
            return cls(year=int(m.group(2)), quarter=m.group(1).capitalize())
        return None


class TermRegistry:
    """Process-wide list of which terms have data loaded."""

    def __init__(self):
        self._terms: set[Term] = set()
        self._default: Optional[Term] = None

    def register(self, term: Term) -> None:
        self._terms.add(term)

    def all(self) -> list[Term]:
        return sorted(self._terms, reverse=True)

    def latest(self) -> Optional[Term]:
        if not self._terms:
            return None
        return max(self._terms)

    def default(self) -> Optional[Term]:
        return self._default or self.latest()

    def set_default(self, term: Term) -> None:
        self._default = term

    def has(self, term: Term) -> bool:
        return term in self._terms


# Module-level singleton
_registry = TermRegistry()


def get_term_registry() -> TermRegistry:
    return _registry
