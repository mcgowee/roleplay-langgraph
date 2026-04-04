#!/usr/bin/env python3
"""Interactive game designer — generates game JSON files for the LangGraph RPG engine."""

import json
import os
from datetime import datetime

from config import GAMES_DIR, DEFAULT_MODEL, SAVE_SLOTS, INVENTORY_WEIGHT_LIMIT

MODELS = [
    "nchapman/mn-12b-mag-mell-r1:latest",
    "dolphin-llama3:8b",
    "dolphin-mistral:latest",
    "dolphin-phi:3b",
    "llama3.1:8b",
    "mistral:7b-instruct",
    "mistral-small:24b",
    "deepseek-r1:14b",
]


def ask(prompt, default=None):
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    while True:
        result = input(f"{prompt}: ").strip()
        if result:
            return result
        print("  (required)")


def ask_list(prompt):
    print(f"{prompt} (comma-separated):")
    items = input("  > ").strip()
    return [i.strip() for i in items.split(",") if i.strip()]


def pick_model(label):
    print(f"\nChoose a model for {label}:")
    for i, m in enumerate(MODELS, 1):
        print(f"  {i}. {m}")
    while True:
        choice = input(f"Pick (1-{len(MODELS)}) [1]: ").strip()
        if not choice:
            return DEFAULT_MODEL
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(MODELS):
                return MODELS[idx]
        except ValueError:
            pass
        print("  Invalid choice.")


def build_character():
    print("\n--- New Character ---")
    name = ask("Character name")
    model = pick_model(name)
    prompt = ask("Character personality/behavior prompt")
    mood = int(ask("Starting mood (1-10)", "5"))
    location = ask("Starting location name")
    first_line = ask("First line of dialogue")

    print(f"\nMood descriptions for {name} (press Enter to skip a level):")
    mood_descriptions = {}
    for level in range(1, 11):
        desc = input(f"  Mood {level}: ").strip()
        if desc:
            mood_descriptions[str(level)] = desc

    return name, {
        "model": model,
        "prompt": prompt,
        "mood": mood,
        "mood_descriptions": mood_descriptions,
        "location": location,
        "first_line": first_line,
    }


def build_location():
    print("\n--- New Location ---")
    name = ask("Location name")
    description = ask("Description")
    items = ask_list("Items in this location")
    characters = ask_list("Characters in this location (by name)")
    return name, {
        "description": description,
        "items": items,
        "characters": characters,
    }


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║              LANGGRAPH RPG — GAME DESIGNER              ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    title = ask("Game title")
    opening = ask("Opening text (shown when game starts)")
    filename = ask("Save as filename (no .json)", title.lower().replace(" ", "_"))

    print(f"\nSave slots available: 0-{SAVE_SLOTS - 1}")
    print("Note: Save slots are managed by the server, not the game design.")
    print("The game will automatically save to slot 0 by default.\n")

    # Narrator
    print("\n--- Narrator ---")
    narrator_model = pick_model("narrator")
    narrator_prompt = ask("Narrator style prompt")

    # Player
    print("\n--- Player Character ---")
    player_name = ask("Player name")
    player_bg = ask("Player background")
    player_traits = ask_list("Player traits")

    # Characters
    characters = {}
    while True:
        name, char = build_character()
        characters[name] = char
        more = input("\nAdd another character? (y/n) [n]: ").strip().lower()
        if more != "y":
            break

    # Locations
    locations = {}
    while True:
        name, loc = build_location()
        locations[name] = loc
        more = input("\nAdd another location? (y/n) [n]: ").strip().lower()
        if more != "y":
            break

    # Rules
    print("\n--- Rules ---")
    win = input("Win condition (or leave blank): ").strip()
    lose = input("Lose condition (or leave blank): ").strip()

    trigger_words = {}
    print("Trigger words (type 'done' to finish):")
    while True:
        trigger = input("  Trigger phrase: ").strip()
        if trigger.lower() == "done" or not trigger:
            break
        response = input("  Response text: ").strip()
        if response:
            trigger_words[trigger] = response

    # Build the game
    game = {
        "title": title,
        "opening": opening,
        "narrator": {
            "model": narrator_model,
            "prompt": narrator_prompt,
        },
        "player": {
            "name": player_name,
            "background": player_bg,
            "traits": player_traits,
        },
        "characters": characters,
        "locations": locations,
        "rules": {
            "win": win,
            "lose": lose,
            "trigger_words": trigger_words,
        },
    }

    # Save
    os.makedirs(GAMES_DIR, exist_ok=True)
    path = os.path.join(GAMES_DIR, f"{filename}.json")
    with open(path, "w") as f:
        json.dump(game, f, indent=2)

    # Create default save slot metadata
    os.makedirs(
        os.path.expanduser("~/projects/roleplay-langgraph/sessions"), exist_ok=True
    )

    print(f"\nGame saved to {path}")
    print("Start the server and play!")
    print("\n" + "=" * 60)
    print("GAME PRODUCTION NOTES:")
    print(f"  - Default inventory weight limit: {INVENTORY_WEIGHT_LIMIT} items")
    print(f"  - Save slots available: 0-{SAVE_SLOTS - 1}")
    print(f"  - Models available: {', '.join(MODELS)}")
    print(f"  - History limit: 6 turns per prompt")
    print("=" * 60)


if __name__ == "__main__":
    main()
