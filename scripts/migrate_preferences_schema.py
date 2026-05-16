#!/usr/bin/env python3
"""
Migrate preferences.json from bare-string format to object-with-id format.

Old shape (Channel B writes this):
    ["Prefers easy courses", "Dislikes morning classes"]

New shape (required for Memory inspection panel — needs per-item delete):
    [
      {"id": "pref_a3f5", "text": "Prefers easy courses",
       "learned_at": "2026-05-13T11:00:00Z"},
      {"id": "pref_b8e2", "text": "Dislikes morning classes",
       "learned_at": "2026-05-13T11:00:00Z"}
    ]

Idempotent — already-migrated files are skipped. Each migrated file gets
a .bak backup next to it for paranoia.

Usage:
    python3 scripts/migrate_preferences_schema.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

MEMORY_DIR = Path("data/memory")


def migrate_file(path: Path, dry_run: bool = False) -> tuple[str, str]:
    """
    Returns (status, reason).
    status ∈ {"migrated", "skipped-already", "skipped-empty", "error"}
    """
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return "error", f"read error: {e}"

    if not isinstance(items, list):
        return "error", f"top-level not a list (got {type(items).__name__})"

    if not items:
        return "skipped-empty", "empty list"

    if isinstance(items[0], dict):
        # Already migrated. Sanity-check shape.
        keys = set(items[0].keys())
        if "id" in keys and "text" in keys:
            return "skipped-already", f"already migrated ({len(items)} items)"
        return "error", f"unexpected dict shape: keys={sorted(keys)}"

    if not isinstance(items[0], str):
        return "error", f"unexpected element type: {type(items[0]).__name__}"

    # Migrate. Use UTC timestamp truncated to seconds; per-item IDs use 6
    # hex chars (24 bits ≈ 16M combinations) which is plenty per user.
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    migrated = [
        {
            "id": "pref_" + secrets.token_hex(3),  # 6 hex chars
            "text": text,
            "learned_at": now,
        }
        for text in items
    ]

    if dry_run:
        return "migrated", f"DRY-RUN — would convert {len(items)} → {len(migrated)} objects"

    # Backup, then overwrite.
    backup = path.with_suffix(".json.bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(
        json.dumps(migrated, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return "migrated", f"converted {len(items)} → {len(migrated)} objects (backup: {backup.name})"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing files")
    parser.add_argument("--memory-dir", default=str(MEMORY_DIR),
                        help=f"Memory root directory (default: {MEMORY_DIR})")
    args = parser.parse_args()

    mem_dir = Path(args.memory_dir)
    if not mem_dir.exists():
        print(f"❌ {mem_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    pref_files = sorted(mem_dir.glob("*/preferences.json"))
    if not pref_files:
        print(f"No preferences.json files under {mem_dir}/")
        return

    print(f"Found {len(pref_files)} preferences.json files"
          + (" (DRY RUN)" if args.dry_run else "") + ":\n")

    counts = {"migrated": 0, "skipped-already": 0, "skipped-empty": 0, "error": 0}
    for pf in pref_files:
        user_id = pf.parent.name
        status, reason = migrate_file(pf, dry_run=args.dry_run)
        counts[status] += 1
        glyph = {"migrated": "✓", "skipped-already": "⏭",
                 "skipped-empty": "·", "error": "✗"}[status]
        print(f"  {glyph} {user_id:24} {reason}")

    print(f"\n{'DRY RUN: ' if args.dry_run else ''}"
          f"{counts['migrated']} migrated · "
          f"{counts['skipped-already']} already · "
          f"{counts['skipped-empty']} empty · "
          f"{counts['error']} errors")


if __name__ == "__main__":
    main()