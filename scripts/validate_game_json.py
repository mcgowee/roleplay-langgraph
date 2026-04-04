#!/usr/bin/env python3
"""
Validate game JSON files for the LangGraph RPG engine (no server, no LLM).

Usage:
  python3 scripts/validate_game_json.py games/my_game.json
  python3 scripts/validate_game_json.py games/*.json
  python3 scripts/validate_game_json.py --all
  python3 scripts/validate_game_json.py --all --strict   # fail on warnings too

Exit codes: 0 ok, 1 errors (or warnings if --strict), 2 file not found / invalid JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import GAMES_DIR  # noqa: E402

ENGINE_FIELDS_DOC = "See games/warehouse.json and GAME_DESIGN_PROMPT.md for the exact schema."


def validate_game(data: dict, filename: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    def err(msg: str) -> None:
        errors.append(f"{filename}: {msg}")

    def warn(msg: str) -> None:
        warnings.append(f"{filename}: {msg}")

    # Top-level noise (engine ignores)
    for key in ("genre", "teaser", "setting", "tone"):
        if key in data:
            warn(f"Top-level '{key}' is ignored by the engine; use 'opening' / narrator.prompt / etc.")

    if not isinstance(data.get("title"), str) or not data["title"].strip():
        err("Missing or empty string 'title'.")

    if "opening" not in data or not (isinstance(data.get("opening"), str) and data["opening"].strip()):
        warn("Missing or empty 'opening' (menu + new-game intro line).")

    # Narrator
    narrator = data.get("narrator")
    if not isinstance(narrator, dict):
        err("'narrator' must be an object with at least 'prompt' and usually 'model'.")
    else:
        if not isinstance(narrator.get("prompt"), str) or not narrator["prompt"].strip():
            err("narrator.prompt is required (non-empty string). 'tone' alone is not used.")
        if not narrator.get("model"):
            warn("narrator.model missing; engine falls back to DEFAULT_MODEL from config.")

    # Player
    player = data.get("player")
    if not isinstance(player, dict):
        err("'player' must be an object with name, background, traits.")
    else:
        if not player.get("name"):
            err("player.name is required.")
        if not player.get("background"):
            warn("player.background empty or missing (engine uses a default).")
        if "personality_traits" in player and "traits" not in player:
            err(
                "player uses 'personality_traits' but the engine reads 'traits'. "
                "Rename to 'traits' (list of strings)."
            )
        if "traits" in player and not isinstance(player["traits"], list):
            err("player.traits must be a list of strings.")
        if "traits" not in player:
            warn("player.traits missing; engine will use [].")

    # Locations
    locations = data.get("locations")
    if not isinstance(locations, dict) or not locations:
        err("'locations' must be a non-empty object.")
    else:
        loc_keys = list(locations.keys())
        start_loc = loc_keys[0]
        for lk, lv in locations.items():
            if not isinstance(lv, dict):
                err(f"locations.{lk} must be an object.")
                continue
            if not isinstance(lv.get("description"), str) or not lv["description"].strip():
                err(f"locations.{lk}.description must be a non-empty string.")
            if "items" not in lv or not isinstance(lv["items"], list):
                err(f"locations.{lk}.items must be a list (can be empty).")
            if "characters" not in lv or not isinstance(lv["characters"], list):
                err(f"locations.{lk}.characters must be a list (can be empty).")
            for cname in lv.get("characters", []):
                if not isinstance(cname, str):
                    err(f"locations.{lk}.characters must be strings (character ids).")

    # Characters (after locations)
    characters = data.get("characters")
    if not isinstance(characters, dict):
        err("'characters' must be an object (can be empty {}).")
    elif locations and isinstance(locations, dict):
        char_ids = set(characters.keys())
        for lk, lv in locations.items():
            if not isinstance(lv, dict):
                continue
            for cname in lv.get("characters", []):
                if cname not in char_ids:
                    err(f"locations.{lk}.characters references '{cname}' but there is no characters.{cname}.")

        for cid, cdata in characters.items():
            if not isinstance(cdata, dict):
                err(f"characters.{cid} must be an object.")
                continue
            if not isinstance(cdata.get("prompt"), str) or not cdata["prompt"].strip():
                err(f"characters.{cid}.prompt is required (non-empty string).")
            if cdata.get("first_line_of_dialogue") and not cdata.get("first_line"):
                err(
                    f"characters.{cid} uses 'first_line_of_dialogue'; engine expects 'first_line'."
                )
            if "starting_location" in cdata and "location" not in cdata:
                err(
                    f"characters.{cid} uses 'starting_location'; engine expects 'location' "
                    "(must match a key in locations)."
                )
            loc_ref = cdata.get("location")
            if loc_ref is not None and loc_ref not in locations:
                err(f"characters.{cid}.location '{loc_ref}' is not a key in locations.")
            if cdata.get("starting_mood") is not None and cdata.get("mood") is None:
                err(f"characters.{cid} uses 'starting_mood'; engine expects 'mood' (number 1–10).")
            md = cdata.get("mood_descriptions")
            if not isinstance(md, dict) or not md:
                warn(f"characters.{cid}.mood_descriptions missing or empty (engine uses generic fallbacks).")
            else:
                for level in range(1, 11):
                    if str(level) not in md:
                        warn(f"characters.{cid}.mood_descriptions missing key '{level}' (1–10 recommended).")
            if not cdata.get("model"):
                warn(f"characters.{cid}.model missing; engine uses DEFAULT_MODEL.")

        # Characters listed at start location should include anyone with first_line
        start_chars = set()
        if start_loc in locations and isinstance(locations.get(start_loc), dict):
            start_chars = set(locations[start_loc].get("characters") or [])
        for cid, cdata in characters.items():
            if not isinstance(cdata, dict):
                continue
            if cdata.get("first_line") and cid not in start_chars:
                warn(
                    f"characters.{cid} has first_line but is not listed in "
                    f"locations.{start_loc}.characters — first line won't show at game start."
                )

    # Rules
    rules = data.get("rules")
    if not isinstance(rules, dict):
        err("'rules' must be an object with win, lose, trigger_words.")
    else:
        if "win_condition" in rules or "lose_condition" in rules:
            err(
                "rules uses win_condition/lose_condition; engine expects 'win' and 'lose' strings."
            )
        if "win" not in rules:
            err("rules.win missing (use \"\" for sandbox).")
        if "lose" not in rules:
            err("rules.lose missing (use \"\" for sandbox).")
        tw = rules.get("trigger_words")
        if tw is not None and not isinstance(tw, dict):
            err("rules.trigger_words must be an object (map phrase -> response).")
        if "trigger_words" in data and data["trigger_words"] is not rules.get("trigger_words"):
            err(
                "trigger_words appears at top level; it must live inside rules as rules.trigger_words."
            )

    return errors, warnings


def validate_path(path: Path) -> tuple[list[str], list[str]]:
    all_err: list[str] = []
    all_warn: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"{path}: Invalid JSON: {e}"], []
    except OSError as e:
        return [f"{path}: {e}"], []

    if not isinstance(data, dict):
        return [f"{path}: Root JSON value must be an object."], []

    e, w = validate_game(data, path.name)
    return e, w


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate RPG game JSON files.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Game JSON files (default with --all: entire games/ folder)",
    )
    parser.add_argument("--all", action="store_true", help=f"Validate every .json in {GAMES_DIR}")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (non-zero exit)",
    )
    args = parser.parse_args()

    if args.all:
        paths = sorted(GAMES_DIR.glob("*.json"))
        if not paths:
            print(f"No .json files in {GAMES_DIR}", file=sys.stderr)
            sys.exit(2)
    elif args.paths:
        paths = args.paths
    else:
        parser.print_help()
        sys.exit(2)

    total_errors: list[str] = []
    total_warnings: list[str] = []

    for p in paths:
        p = p.resolve()
        if not p.is_file():
            print(f"Not a file: {p}", file=sys.stderr)
            total_errors.append(f"{p}: file not found")
            continue
        e, w = validate_path(p)
        total_errors.extend(e)
        total_warnings.extend(w)

    for line in total_errors:
        print(f"ERROR: {line}", file=sys.stderr)
    for line in total_warnings:
        print(f"WARN: {line}", file=sys.stderr)

    if total_errors:
        print(f"\n{ENGINE_FIELDS_DOC}", file=sys.stderr)
        sys.exit(1)
    if total_warnings and args.strict:
        print(f"\n{ENGINE_FIELDS_DOC}", file=sys.stderr)
        sys.exit(1)

    if paths:
        print(f"OK: {len(paths)} file(s) validated.")
    sys.exit(0)


if __name__ == "__main__":
    main()
