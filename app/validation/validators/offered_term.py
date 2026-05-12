"""
offered_term validator — catches courses recommended that aren't
actually offered in the target term, plus emits a historical-proxy
disclaimer when source_term != target_term.

This is a redundant safety net: query.py SHOULD only return offered
courses, but if a future refactor drops that guarantee, this catches it.
"""

from __future__ import annotations

from app.validation.types import (
    Issue, Severity, SuggestedAction, ValidationContext,
)
from app.validation.validators.base import Validator


class OfferedTermValidator(Validator):
    @property
    def name(self) -> str:
        return "offered_term"

    def check(self, ctx: ValidationContext) -> list[Issue]:
        issues: list[Issue] = []

        # ── 1. Historical-proxy disclaimer ──
        prov = ctx.catalog.provenance
        if prov is not None and prov.is_historical_proxy:
            issues.append(Issue(
                validator=self.name,
                code="HISTORICAL_PROXY_DATA",
                severity=Severity.INFO,
                message=(
                    f"Data shown is from {prov.source_term} as a stand-in for "
                    f"{prov.target_term}. Section availability and instructors "
                    f"may differ in the actual term."
                ),
                evidence={
                    "source_term": prov.source_term,
                    "target_term": prov.target_term,
                },
                suggested_action=SuggestedAction.ANNOTATE,
            ))

        # ── 2. Each retrieved primary must be offered this term ──
        # NOTE: During Phase 1 with mock_data, query.py returns courses that
        # may not exist in the real UCI catalog for the target term. This is
        # mostly a data-source mismatch issue (mock_data ↔ real catalog),
        # not an LLM hallucination. We emit WARN, not ERROR, until query.py
        # is migrated to the real data source.
        for ref in ctx.retrieved_primary_refs:
            if not ctx.catalog.offered_this_term(ref):
                issues.append(Issue(
                    validator=self.name,
                    code="QUERY_RECOMMENDED_NOT_OFFERED",
                    severity=Severity.WARN,
                    message=(
                        f"{ref.display()} was recommended by the query system "
                        f"but has no sections in {ctx.catalog.target_term.display()} "
                        f"per our catalog data. May indicate a mock_data ↔ "
                        f"catalog mismatch (expected during Phase 1)."
                    ),
                    evidence={"ref": ref.display()},
                    suggested_action=SuggestedAction.ANNOTATE,
                ))
        return issues
