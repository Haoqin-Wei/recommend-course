#!/usr/bin/env python3
"""
One-time migration: old single-conversation `turn_log.jsonl` → "Legacy chat"
session under the new sessions/ folder structure.

Before:
    data/memory/demo_001/
    ├── profile.json
    ├── preferences.json
    ├── facts.json
    └── turn_log.jsonl              ← single rolling log

After:
    data/memory/demo_001/
    ├── profile.json                ← unchanged
    ├── preferences.json            ← unchanged
    ├── facts.json                  ← unchanged
    ├── turn_log.jsonl.legacy       ← renamed (non-destructive)
    └── sessions/
        └── sess_legacy_XXXXXX/
            ├── meta.json           (title: "Legacy chat from {date}")
            └── turns.jsonl         (turns extracted from old log)

Idempotent — running twice does nothing the second time (detects .legacy
extension and bails). The script does NOT delete the original log; if you
want to be safe, leave the .legacy file around for a week before deleting.

Field mapping for old → new turn format:
    {"role": ..., "content": ..., "timestamp": ...}
                  ↓
    {"turn_index": N, "role": ..., "content": ..., "timestamp": ...}

Unrecognized roles are skipped (e.g. "system" / "tool" entries).

Usage:
    python3 scripts/migrate_sessions_schema.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure we can import the data-layer module regardless of cwd
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from app.data import sessions as S


MEMORY_DIR = REPO_ROOT / "data" / "memory"

VALID_ROLES = {"user", "assistant"}


def _extract_turns_from_row(row: dict) -> list[dict]:
    """
    Extract 0, 1, or 2 turns from one old turn_log row.

    Supports two historical formats:

      Format A — paired exchange (the format demo_001 actually uses):
        {"ts": ..., "session_id": ..., "user": "...", "assistant": "..."}
        → yields 2 turns (one user, one assistant).

      Format B — role-tagged single turn:
        {"role": "user"|"assistant", "content": "...", "timestamp": ...}
        → yields 1 turn.

    Returns [] for rows that match neither (silently skipped).
    """
    timestamp = (row.get("ts") or row.get("timestamp") or row.get("at") or "")

    # Format A: paired exchange
    if isinstance(row.get("user"), str) and isinstance(row.get("assistant"), str):
        return [
            {"role": "user",
             "content": row["user"],
             "timestamp": timestamp},
            {"role": "assistant",
             "content": row["assistant"],
             "timestamp": timestamp},
        ]

    # Format B: role-tagged single
    role = row.get("role")
    content = row.get("content") or row.get("text") or row.get("message")
    if role in VALID_ROLES and content:
        return [{"role": role, "content": str(content), "timestamp": timestamp}]

    return []


def _migrate_user(user_dir: Path, dry_run: bool) -> tuple[str, str]:
    """
    Migrate one user's turn_log.jsonl. Returns (status, reason).
    status ∈ {"migrated", "skipped-no-log", "skipped-already", "error"}
    """
    user_id = user_dir.name
    old_log = user_dir / "turn_log.jsonl"
    legacy_marker = user_dir / "turn_log.jsonl.legacy"

    if not old_log.exists() and legacy_marker.exists():
        return "skipped-already", "already migrated (turn_log.jsonl.legacy exists)"
    if not old_log.exists():
        return "skipped-no-log", "no turn_log.jsonl to migrate"

    # Read old rows
    rows: list[dict] = []
    with old_log.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Expand rows → turns (paired rows yield 2 turns each)
    valid_turns: list[dict] = []
    for r in rows:
        valid_turns.extend(_extract_turns_from_row(r))

    if not valid_turns:
        return "skipped-no-log", (
            f"log had {len(rows)} rows but none matched a known format "
            f"({{role,content}} or {{user,assistant}})"
        )

    # Title from earliest timestamp
    first_ts = valid_turns[0].get("timestamp") or datetime.now(timezone.utc).isoformat()
    try:
        date_str = first_ts[:10]   # YYYY-MM-DD
    except Exception:
        date_str = "unknown date"
    title = f"Legacy chat from {date_str}"

    if dry_run:
        return "migrated", (
            f"DRY-RUN — would create session with {len(valid_turns)} turns "
            f"({len(rows)} source rows), title={title!r}"
        )

    # Create + populate via the data layer
    session_id = S.create_session(user_id, title=title, term_scope=None)
    for turn in valid_turns:
        S.append_turn(user_id, session_id, turn["role"], turn["content"])

    # Rename the old log (non-destructive)
    old_log.rename(legacy_marker)

    return "migrated", (
        f"created {session_id} with {len(valid_turns)} turns "
        f"from {len(rows)} source rows (old log → .legacy)"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would happen without writing files")
    ap.add_argument("--memory-dir", default=str(MEMORY_DIR),
                    help=f"Memory root directory (default: {MEMORY_DIR})")
    args = ap.parse_args()

    mem_dir = Path(args.memory_dir)
    if not mem_dir.exists():
        print(f"❌ {mem_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    # Update sessions module's MEMORY_ROOT if a custom dir was passed
    S.MEMORY_ROOT = mem_dir

    user_dirs = sorted([d for d in mem_dir.iterdir() if d.is_dir()])
    if not user_dirs:
        print(f"No user directories under {mem_dir}/")
        return

    header = "DRY RUN: " if args.dry_run else ""
    print(f"{header}Scanning {len(user_dirs)} user directories under {mem_dir}/\n")

    counts = {"migrated": 0, "skipped-already": 0, "skipped-no-log": 0, "error": 0}
    for ud in user_dirs:
        try:
            status, reason = _migrate_user(ud, dry_run=args.dry_run)
        except Exception as e:
            status, reason = "error", f"{type(e).__name__}: {e}"
        counts[status] += 1

        glyph = {"migrated": "✓", "skipped-already": "⏭",
                 "skipped-no-log": "·", "error": "✗"}[status]
        print(f"  {glyph} {ud.name:24} {reason}")

    print(f"\n{header}"
          f"{counts['migrated']} migrated · "
          f"{counts['skipped-already']} already · "
          f"{counts['skipped-no-log']} no log · "
          f"{counts['error']} errors")


if __name__ == "__main__":
    main()