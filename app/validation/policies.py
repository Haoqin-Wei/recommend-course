"""
Policy — given a ValidationReport, decide how to apply it.

Phase 1 policy: very permissive.
  - Any issues → ANNOTATE (footer summary, original answer preserved)
  - REWRITE / BLOCK are coded behind flags but disabled. Flip them on
    after a week of validation_log.jsonl observation.

Thresholds are constants here for easy tuning.
"""

from __future__ import annotations

from app.validation.types import ValidationReport, SuggestedAction


# Phase 1: never block, only annotate. Flip these once we trust the
# validators and have enough sample data to set thresholds.
ENABLE_REWRITE = False
ENABLE_BLOCK = False

# When BLOCK is enabled, this many errors triggers it.
BLOCK_THRESHOLD_ERRORS = 2


def decide_action(report: ValidationReport) -> SuggestedAction:
    if ENABLE_BLOCK and len(report.errors) >= BLOCK_THRESHOLD_ERRORS:
        return SuggestedAction.BLOCK
    if ENABLE_REWRITE and report.errors:
        return SuggestedAction.REMOVE
    if report.issues:
        return SuggestedAction.ANNOTATE
    return SuggestedAction.KEEP
