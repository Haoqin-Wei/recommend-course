"""
instructor validator — checks professor names mentioned in LLM output.

For every 'Professor X' style mention:
  - Resolve X to a surname guess (last capitalized token)
  - No instructor in catalog with this surname → WARN
  - Multiple instructors share this surname → INFO (ambiguous)
  - Exactly one match → silently OK

We REQUIRE the 'Professor'/'Prof.'/'Instructor' keyword before the name
to avoid false positives on bare last names like "Thornton".

PHASE 1 NOTE on severity: An unknown surname in our single-term data
may genuinely be hallucinated, OR it may be a real UCI professor who
just doesn't teach in this particular term (mock_data ↔ real-data
mismatch — same root cause as offered_term WARN). Until query.py is
migrated to real data and / or we load multiple terms simultaneously,
we cannot distinguish those cases, so we emit WARN, not ERROR.
"""

from __future__ import annotations

from app.catalog.normalization import iter_instructor_mentions
from app.validation.types import (
    Issue, Severity, SuggestedAction, ValidationContext,
)
from app.validation.validators.base import Validator


class InstructorValidator(Validator):
    @property
    def name(self) -> str:
        return "instructor"

    def check(self, ctx: ValidationContext) -> list[Issue]:
        issues: list[Issue] = []
        seen_unknown: set[str] = set()
        seen_ambiguous: set[str] = set()

        for surname, start, end in iter_instructor_mentions(ctx.llm_answer):
            matches = ctx.catalog.find_instructors_by_last_name(surname)

            if not matches:
                if surname in seen_unknown:
                    continue
                seen_unknown.add(surname)
                issues.append(Issue(
                    validator=self.name,
                    code="UNKNOWN_INSTRUCTOR",
                    severity=Severity.WARN,
                    message=(
                        f"LLM referenced 'Professor {surname.title()}', but no "
                        f"instructor with surname '{surname}' is on record for "
                        f"{ctx.catalog.target_term.display()}. May be a "
                        f"hallucinated name, or a real professor not teaching "
                        f"this term (mock_data ↔ catalog mismatch expected "
                        f"during Phase 1)."
                    ),
                    location={
                        "start": start, "end": end,
                        "snippet": ctx.llm_answer[start:end],
                    },
                    evidence={"surname": surname, "candidates": []},
                    suggested_action=SuggestedAction.ANNOTATE,
                ))
            elif len(matches) > 1:
                if surname in seen_ambiguous:
                    continue
                seen_ambiguous.add(surname)
                issues.append(Issue(
                    validator=self.name,
                    code="AMBIGUOUS_INSTRUCTOR",
                    severity=Severity.INFO,
                    message=(
                        f"Multiple instructors share surname '{surname}': "
                        f"{', '.join(matches)}. LLM didn't specify which."
                    ),
                    location={
                        "start": start, "end": end,
                        "snippet": ctx.llm_answer[start:end],
                    },
                    evidence={"surname": surname, "candidates": matches},
                    suggested_action=SuggestedAction.KEEP,
                ))
        return issues
