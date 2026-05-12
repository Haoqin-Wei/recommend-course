"""
Apply a ValidationReport to the chat response.

Phase 1 modes:
  - KEEP:     return the answer untouched
  - ANNOTATE: append a footer summarizing issues
  - REMOVE:   placeholder for Phase 2 (currently falls back to ANNOTATE)
  - BLOCK:    placeholder for Phase 2 (currently falls back to ANNOTATE)
"""

from __future__ import annotations
import logging

from app.validation.types import (
    ValidationReport, SuggestedAction, Severity,
)

logger = logging.getLogger(__name__)


def apply_report(
    answer: str,
    cards: list[dict],
    report: ValidationReport,
    action: SuggestedAction,
) -> tuple[str, list[dict], bool]:
    """Return (final_answer, final_cards, was_modified)."""

    if action == SuggestedAction.KEEP or not report.issues:
        return answer, cards, False

    if action == SuggestedAction.ANNOTATE:
        return answer + _build_footer(report), cards, True

    if action == SuggestedAction.REMOVE:
        logger.warning(
            "REMOVE requested but not implemented in Phase 1; annotating instead"
        )
        return answer + _build_footer(report), cards, True

    if action == SuggestedAction.BLOCK:
        logger.warning(
            "BLOCK requested but not implemented in Phase 1; annotating instead"
        )
        return answer + _build_footer(report), cards, True

    return answer, cards, False


def _build_footer(report: ValidationReport) -> str:
    """Build a markdown footer summarizing validation findings."""
    if not report.issues:
        return ""

    sev_icons = {
        Severity.ERROR: "❌",
        Severity.WARN: "⚠️",
        Severity.INFO: "ℹ️",
    }

    lines = ["\n\n---\n", "**🔍 Data check:**"]
    by_sev: dict[Severity, list] = {s: [] for s in Severity}
    for issue in report.issues:
        by_sev[issue.severity].append(issue)

    for sev in (Severity.ERROR, Severity.WARN, Severity.INFO):
        for issue in by_sev[sev]:
            lines.append(f"- {sev_icons[sev]} {issue.message}")
    return "\n".join(lines)
