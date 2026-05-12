"""
Validation logging — append-only JSONL for offline analysis.

One line per validation pass. Used for:
  - Regression testing (replay past LLM outputs against current validators)
  - Tuning thresholds (deciding when to escalate ANNOTATE → REWRITE → BLOCK)
  - Spotting prompt drift over time
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.validation.types import (
    ValidationContext, ValidationReport, SuggestedAction,
)

logger = logging.getLogger(__name__)


LOG_DIR = Path("data/logs")
LOG_FILE = LOG_DIR / "validation.jsonl"


def write_log(
    ctx: ValidationContext,
    report: ValidationReport,
    action: SuggestedAction,
    final_answer_changed: bool,
    session_id: Optional[str] = None,
) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        prov = ctx.catalog.provenance
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "user_message": ctx.user_message,
            "llm_raw_answer": ctx.llm_answer,
            "target_term": ctx.catalog.target_term.term_id,
            "provenance": {
                "source_term": prov.source_term if prov else None,
                "loader": prov.loader if prov else None,
            },
            "retrieved_summary": {
                "primary_ids": [r.display() for r in ctx.retrieved_primary_refs],
                "flagged_ids": [r.display() for r in ctx.retrieved_flagged_refs],
            },
            "report": report.to_dict(),
            "applied_action": action.value,
            "final_answer_changed": final_answer_changed,
        }
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Failed to write validation log: %s", e)
