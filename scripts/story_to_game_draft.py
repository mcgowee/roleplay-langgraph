#!/usr/bin/env python3
"""
Turn a prose story file into a draft games/*.json using local Ollama (no Flask).

  python3 scripts/story_to_game_draft.py my_story.txt -o games/from_story.json
  python3 scripts/story_to_game_draft.py my_story.txt --dry-run   # print prompt only

Then: python3 scripts/validate_game_json.py games/from_story.json

Requires: requests (`pip install requests`), Ollama running (OLLAMA_HOST / model from config or -m).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DEFAULT_MODEL, OLLAMA_HOST  # noqa: E402

# Shown in documents/STORY_TO_GAME.md — keep in sync for copy-paste into chats.
STORY_TO_GAME_INSTRUCTIONS = """
You are converting narrative prose into ONE JSON object for a text-based RPG engine.

Output rules:
- Output ONLY a single JSON object. No markdown code fences, no commentary before or after.
- Use the exact keys and nesting below. Field names must match exactly (the engine does not read "tone", "win_condition", or "personality_traits").

Required shape (fill every string/list/object; use "" or [] or {} where appropriate):

{
  "title": "",
  "opening": "",
  "narrator": {
    "model": "",
    "prompt": ""
  },
  "player": {
    "name": "",
    "background": "",
    "traits": []
  },
  "characters": {
    "lowercase_id": {
      "model": "",
      "prompt": "",
      "mood": 5,
      "mood_descriptions": { "1": "", "2": "", ... "10": "" },
      "location": "",
      "first_line": ""
    }
  },
  "locations": {
    "lowercase_key": {
      "description": "",
      "items": [],
      "characters": []
    }
  },
  "rules": {
    "win": "",
    "lose": "",
    "trigger_words": {}
  }
}

Schema rules:
- Character keys and locations[].characters[] use the same lowercase ids.
- characters.<id>.location must equal a key in locations.
- The FIRST key in "locations" is where the player starts.
- narrate in second person via narrator.prompt; narrator never speaks as NPCs.
- rules.trigger_words maps short distinctive phrases (substring match) to fixed responses.
- Put trigger_words INSIDE rules, not at the top level.
- win / lose are plain English for an LLM judge; leave "" if sandbox.

Infer models from the story tone or use a sensible default like "llama3.1:8b" for narrator.

Hard requirements (validator will fail if broken):
- player.name must be a non-empty string (protagonist name from the story).
- narrator.prompt must be a full behavior spec (second person, tone, length, end with "What do you do?") — not a single question to the user.
- Every character with a non-empty first_line slot in the starting location must have characters.<id>.first_line non-empty dialogue.

Now convert the following story into that JSON object.
""".strip()

DEFAULT_NARRATOR_FALLBACK = (
    "You are the narrator for a text adventure. Describe scenes in second person. "
    "Do not speak as NPCs. Keep beats concise. End with: What do you do?"
)


def repair_draft(data: dict, story_text: str) -> tuple[dict, list[str]]:
    """Fill obvious gaps models often leave empty. Returns (data, warning lines)."""
    notes: list[str] = []
    st = story_text[:4000]

    player = dict(data.get("player") or {})
    original_name = (player.get("name") or "").strip()
    name = original_name
    if not name:
        opening = data.get("opening") or ""
        m0 = re.search(r"You(?:'re| are)\s+([A-Za-z]+)", opening)
        if m0:
            name = m0.group(1).strip()
    if not name:
        m = re.search(r"\bprotagonist,?\s+([A-Z][a-z]+)\b", st, re.I)
        if not m:
            m = re.search(
                r"\b(?:^|\n)\s*The ([A-Z][a-z]+),|\b([A-Z][a-z]+),?\s+(?:is|was)\s+(?:a|the)",
                st,
            )
        if m:
            name = next((g for g in m.groups() if g), "").strip()
    if not name:
        m2 = re.search(r"\b([A-Z][a-z]+)'s\b", st)
        if m2:
            name = m2.group(1).strip()
    if not name:
        name = "Player"
        notes.append("Filled empty player.name with 'Player' (add the real name in JSON).")
    elif not original_name:
        notes.append(f"Inferred player.name as {name!r}; confirm in JSON.")
    player["name"] = name
    data["player"] = player

    narrator = dict(data.get("narrator") or {})
    np = (narrator.get("prompt") or "").strip()
    if len(np) < 80:
        narrator["prompt"] = DEFAULT_NARRATOR_FALLBACK
        notes.append("Replaced short narrator.prompt with a safe default (edit for your tone).")
    if not (narrator.get("model") or "").strip():
        narrator["model"] = "llama3.1:8b"
    data["narrator"] = narrator

    locations = data.get("locations") or {}
    first_loc = next(iter(locations.keys()), None)
    start_npcs: set[str] = set()
    if first_loc and isinstance(locations.get(first_loc), dict):
        start_npcs = set(locations[first_loc].get("characters") or [])

    characters = dict(data.get("characters") or {})
    for cid, cdata in list(characters.items()):
        if not isinstance(cdata, dict):
            continue
        cd = dict(cdata)
        fl = (cd.get("first_line") or "").strip()
        if cid in start_npcs and not fl:
            cd["first_line"] = "Well? We don't have all night."
            notes.append(f"Filled empty characters.{cid}.first_line with placeholder line.")
        characters[cid] = cd
    data["characters"] = characters

    return data, notes


def extract_json_object(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model output.")
    return json.loads(text[start : end + 1])


def ollama_generate(host: str, model: str, prompt: str, timeout: int = 600) -> str:
    try:
        import requests
    except ImportError as e:
        raise SystemExit("Install requests: pip install requests") from e

    host = host.rstrip("/")
    url = f"{host}/api/generate"
    r = requests.post(
        url,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    return body.get("response", "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft game JSON from a story via Ollama.")
    parser.add_argument("story", type=Path, help="Path to a .txt (or .md) story file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write JSON here (e.g. games/my_game.json)",
    )
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--host", default=OLLAMA_HOST, help="Ollama base URL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the full prompt and exit (no API call)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip running validate_game_json.py after write",
    )
    args = parser.parse_args()

    story_path = args.story
    if not story_path.is_file():
        print(f"Not a file: {story_path}", file=sys.stderr)
        sys.exit(2)

    story_text = story_path.read_text(encoding="utf-8", errors="replace")
    if not story_text.strip():
        print("Story file is empty.", file=sys.stderr)
        sys.exit(2)

    prompt = f"{STORY_TO_GAME_INSTRUCTIONS}\n\n--- STORY ---\n\n{story_text}\n"

    if args.dry_run:
        print(prompt)
        return

    print(f"Calling Ollama model {args.model!r} at {args.host} …", file=sys.stderr)
    try:
        raw = ollama_generate(args.host, args.model, prompt)
    except Exception as e:
        print(f"Ollama request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not raw.strip():
        print("Empty response from Ollama.", file=sys.stderr)
        sys.exit(1)

    try:
        data = extract_json_object(raw)
        data, repairs = repair_draft(data, story_text)
        for line in repairs:
            print(f"NOTE: {line}", file=sys.stderr)
    except (json.JSONDecodeError, ValueError) as e:
        dump = story_path.with_suffix(story_path.suffix + ".ollama_raw.txt")
        dump.write_text(raw, encoding="utf-8")
        print(
            f"Could not parse JSON: {e}\nRaw response saved to {dump}",
            file=sys.stderr,
        )
        sys.exit(1)

    out = args.output
    if not out:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out}", file=sys.stderr)

    if not args.no_validate:
        v = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_game_json.py"), str(out)],
            cwd=str(ROOT),
        )
        if v.returncode != 0:
            sys.exit(v.returncode)


if __name__ == "__main__":
    main()
