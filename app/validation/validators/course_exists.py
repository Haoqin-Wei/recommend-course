"""
course_exists validator — catches hallucinated course IDs.

For every course mention in the LLM answer:
  - In retrieved.primary or .flagged → silently OK (it's part of the
    recommendation context)
  - In catalog but NOT in retrieved → INFO 'lateral mention' (LLM is
    making a comparison; not wrong but worth logging)
  - Not in catalog at all → ERROR 'HALLUCINATED_COURSE_ID'
"""

from __future__ import annotations

from app.catalog.normalization import iter_course_mentions
from app.validation.types import (
    Issue, Severity, SuggestedAction, ValidationContext,
)
from app.validation.validators.base import Validator


class CourseExistsValidator(Validator):
    @property
    def name(self) -> str:
        return "course_exists"

    def check(self, ctx: ValidationContext) -> list[Issue]:
        issues: list[Issue] = []
        retrieved = ctx.all_retrieved_refs
        seen_hallucinated: set[str] = set()
        seen_lateral: set[str] = set()

        for ref, start, end in iter_course_mentions(ctx.llm_answer):
            if ref in retrieved:
                continue   # recommended course, fine

            if ctx.catalog.course_exists(ref):
                key = ref.display()
                if key in seen_lateral:
                    continue
                seen_lateral.add(key)
                issues.append(Issue(
                    validator=self.name,
                    code="LATERAL_COURSE_MENTION",
                    severity=Severity.INFO,
                    message=(
                        f"LLM mentioned {ref.display()}, which exists in the "
                        f"catalog but was not in this turn's retrieval set."
                    ),
                    location={
                        "start": start, "end": end,
                        "snippet": ctx.llm_answer[start:end],
                    },
                    evidence={
                        "ref": ref.display(),
                        "in_catalog": True, "in_retrieval": False,
                    },
                    suggested_action=SuggestedAction.KEEP,
                ))
                continue

            # Not in catalog at all → hallucinated
            key = ref.display()
            if key in seen_hallucinated:
                continue
            seen_hallucinated.add(key)
            issues.append(Issue(
                validator=self.name,
                code="HALLUCINATED_COURSE_ID",
                severity=Severity.ERROR,
                message=(
                    f"LLM mentioned {ref.display()}, but no such course "
                    f"exists in our data for {ctx.catalog.target_term.display()}."
                ),
                location={
                    "start": start, "end": end,
                    "snippet": ctx.llm_answer[start:end],
                },
                evidence={
                    "ref": ref.display(),
                    "in_catalog": False, "in_retrieval": False,
                },
                suggested_action=SuggestedAction.REMOVE,
            ))
        return issues
