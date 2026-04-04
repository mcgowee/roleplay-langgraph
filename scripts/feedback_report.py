#!/usr/bin/env python3
"""
Summarize playtest feedback JSONL for designing the next game revision or a new game.

Reads all feedback_*.jsonl files under FEEDBACK_DIR (from config / env).

Examples:
  python scripts/feedback_report.py
  python scripts/feedback_report.py --game warehouse
  python scripts/feedback_report.py --brief > /tmp/design_input.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Repo root = parent of scripts/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import FEEDBACK_DIR  # noqa: E402


def load_records(feedback_dir: Path) -> list[dict]:
    records: list[dict] = []
    if not feedback_dir.is_dir():
        return records
    for path in sorted(feedback_dir.glob("feedback_*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize feedback JSONL for game design.")
    parser.add_argument(
        "--game",
        metavar="FILE_STEM",
        help="Only include entries where game_file matches (e.g. warehouse)",
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="Emit a single copy-paste block for an LLM or design notes",
    )
    args = parser.parse_args()

    records = load_records(FEEDBACK_DIR)
    if args.game:
        g = args.game.lower().strip()
        records = [r for r in records if (r.get("game_file") or "").lower() == g]

    if not records:
        print(f"No feedback records in {FEEDBACK_DIR}", file=sys.stderr)
        sys.exit(1)

    if args.brief:
        by_game: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            key = r.get("game_file") or "unknown"
            by_game[key].append(r)

        print("## Playtest feedback — use this to revise or design the next game\n")
        for game_file in sorted(by_game.keys()):
            rows = by_game[game_file]
            title = rows[0].get("game_title") or game_file
            print(f"### Game: {title} (`{game_file}.json`)\n")
            for r in rows:
                cat = r.get("category", "general")
                ts = (r.get("ts") or "")[:19]
                loc = r.get("location", "?")
                turn = r.get("turn_count", "?")
                print(f"- **[{cat}]** ({ts} | {loc} | turn ~{turn}) {r.get('text', '')}")
            print()
        print(
            "### Suggested next step\n"
            "Paste the block above (plus your `games/<name>.json` if revising) into a chat "
            "with `GAME_DESIGN_PROMPT.md` and ask for: concrete JSON edits, new "
            "`trigger_words`, narrator/NPC prompt changes, or a brand-new game JSON.\n"
        )
        return

    print(f"Feedback directory: {FEEDBACK_DIR}\n")
    print(f"Total entries: {len(records)}\n")

    by_cat = Counter(r.get("category", "general") for r in records)
    print("By category:")
    for cat, n in by_cat.most_common():
        print(f"  {cat}: {n}")
    print()

    by_game = Counter((r.get("game_file") or "?") for r in records)
    print("By game_file:")
    for gf, n in by_game.most_common():
        print(f"  {gf}: {n}")
    print()

    print("Entries (newest last in file order):")
    for r in records:
        ts = (r.get("ts") or "")[:19]
        gf = r.get("game_file", "?")
        cat = r.get("category", "general")
        loc = r.get("location", "?")
        turn = r.get("turn_count", "?")
        text = (r.get("text") or "").replace("\n", " ")[:120]
        print(f"  {ts} | {gf} | {cat} | {loc} t{turn} | {text}")


if __name__ == "__main__":
    main()
