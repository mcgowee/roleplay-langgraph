from flask import Flask, g, jsonify, request, session
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional, NotRequired
import importlib.util
import json
import os
import secrets
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from auth import check_password, hash_password, login_required
from config import (
    DEFAULT_MODEL,
    GAMES_DIR,
    GRAPHS_DIR,
    LOGS_DIR,
    FEEDBACK_DIR,
    HISTORY_LIMIT,
    SAVE_SLOTS,
    INVENTORY_WEIGHT_LIMIT,
    FLASK_HOST,
    FLASK_PORT,
    FLASK_DEBUG,
    SECRET_KEY,
)
from db import get_db, init_db, seed_global_games
from llm import get_llm
from logger import get_logger

logger = get_logger(__name__)

DEFAULT_NARRATOR_PROMPT = (
    "You are the narrator for a text adventure. Describe scenes in second person. "
    "Do not speak as an NPC. End each beat with: What do you do?"
)

app = Flask(__name__)
app.secret_key = SECRET_KEY
if not FLASK_DEBUG:
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"):
        app.config["SESSION_COOKIE_SECURE"] = True

FEEDBACK_CATEGORIES = frozenset(
    {"general", "confusing", "bug", "praise", "idea", "pacing", "tone", "other"}
)
FEEDBACK_TEXT_MAX = 8000

if os.environ.get("SECRET_KEY") is None and not FLASK_DEBUG:
    logger.warning(
        "SECRET_KEY is not set in the environment — using a built-in default. "
        "Set SECRET_KEY for production so sessions cannot be forged."
    )


def _llm_public_error_message(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "rate" in msg and "limit" in msg:
        return "The AI service is rate-limited. Try again in a few minutes."
    if "content" in msg and "policy" in msg:
        return "The request was blocked by content safety rules. Revise the text and try again."
    if "401" in msg or "403" in msg or "unauthorized" in msg:
        return "AI service authentication failed. Check server configuration."
    if (
        "connection" in msg
        or "refused" in msg
        or "timeout" in msg
        or "connect" in msg
        or "name or service not known" in msg
    ):
        return "Could not reach the AI service. Check that it is running and reachable."
    return "The AI request failed. Try again later."


def _validation_errors_for_game(data: dict) -> list[str]:
    path = Path(__file__).resolve().parent / "scripts" / "validate_game_json.py"
    if not path.is_file():
        logger.warning("validate_game_json.py not found; skipping schema validation")
        return []
    spec = importlib.util.spec_from_file_location("validate_game_json", path)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    errors, _warnings = mod.validate_game(data, "game.json")
    return errors


# --- Input sanitization ---
def sanitize_input(text: str) -> str:
    """Remove potential prompt injection attempts."""
    dangerous_patterns = [
        "ignore previous instructions",
        "disregard earlier commands",
        "become the",
        "you are now",
        "system override",
    ]
    text_lower = text.lower()
    for pattern in dangerous_patterns:
        if pattern in text_lower:
            logger.warning(f"Blocked potentially dangerous input: {text[:50]}...")
            return "[Input blocked: contains restricted content]"
    return text


# --- Circular buffer for history ---
def add_to_history(history: list, turn: str, limit: int = HISTORY_LIMIT) -> list:
    """Add turn to history, maintaining Circular buffer with limit."""
    history.append(turn)
    while len(history) > limit:
        history.pop(0)
    return history


def _normalize_detector_reply(text: str) -> str:
    """First line only; strip whitespace and simple wrapping quotes/backticks."""
    s = (text or "").strip()
    if not s:
        return ""
    line = s.split("\n", 1)[0].strip()
    if len(line) >= 2 and line[0] == line[-1] and line[0] in "\"'`":
        line = line[1:-1].strip()
    return line


def _build_narrative_engine_brief(state: dict) -> str:
    """Summarize engine-resolved changes this turn for the narrator (ground truth)."""
    snap = state.get("narrative_turn_snapshot")
    if not isinstance(snap, dict):
        return ""
    loc0 = snap.get("location")
    if not isinstance(loc0, str) or not loc0:
        return ""
    inv0 = list(snap.get("inventory") or [])
    room0 = list(snap.get("room_item_names") or [])

    loc1 = state.get("location") or loc0
    inv1 = list(state.get("inventory") or [])
    room = state.get("locations", {}).get(loc1, {}) or {}
    if not isinstance(room, dict):
        room = {}
    room_items1 = list(room.get("items") or [])

    lines: list[str] = []
    if loc1 != loc0:
        lines.append(
            f"- Location changed this turn: {loc0} → {loc1}. You are now in {loc1}; "
            "describe the new place — do not contradict this."
        )
    else:
        lines.append(f"- Location unchanged: still in {loc1}.")

    if inv1 != inv0:
        added = [x for x in inv1 if x not in inv0]
        removed = [x for x in inv0 if x not in inv1]
        if added:
            lines.append(
                f"- The engine recorded a successful pickup: {', '.join(added)}. "
                "The player is carrying these; reflect that naturally."
            )
        if removed:
            lines.append(
                f"- Items left the player's inventory this turn: {', '.join(removed)}."
            )
    else:
        lines.append(
            "- No successful pickup this turn (inventory unchanged by the engine)."
        )

    if loc1 == loc0 and sorted(room_items1) != sorted(room0):
        lines.append(
            f"- Items currently in this room (authoritative): "
            f"{', '.join(room_items1) if room_items1 else 'none'}."
        )

    here = ", ".join(room.get("characters") or []) or "none"
    lines.append(f"- Characters present in this location (IDs): {here}.")

    return (
        "Authoritative facts from the game engine — your prose must match these "
        "(do not invent different locations, items, or pickups):\n"
        + "\n".join(lines)
    )


def _format_milestone_context(state: dict) -> str:
    """Current milestone goal for LLM prompts (social graph and any game with milestones)."""
    milestones = state.get("milestones") or []
    if not milestones:
        return ""
    progress = int(state.get("milestone_progress", 0) or 0)
    total = len(milestones)
    if progress >= total:
        return (
            "Story milestones: all completed. The player has finished the scripted sequence."
        )
    current = milestones[progress]
    done = progress
    return (
        f"Story milestones: {done} of {total} completed so far. "
        f"The player's current goal is: {current}. "
        "When it fits the scene, steer naturally toward this goal without forcing it."
    )


def _format_mood_context_for_room(state: dict) -> str:
    """Summarize NPC moods in the current room for the narrator (no raw numbers in player-facing prose)."""
    loc_key = state.get("location") or ""
    room = (state.get("locations") or {}).get(loc_key) or {}
    if not isinstance(room, dict):
        return ""
    names = room.get("characters") or []
    characters = state.get("characters") or {}
    lines: list[str] = []
    for name in names:
        npc = characters.get(name)
        if not isinstance(npc, dict):
            continue
        mood = int(npc.get("mood", 5) or 5)
        mood = max(1, min(10, mood))
        mood_descriptions = npc.get("mood_descriptions") or {}
        mood_desc = mood_descriptions.get(str(mood), f"about mood level {mood} on a 1–10 scale.")
        tension_desc = _get_tension_description(state, name)
        if tension_desc:
            mood_desc = tension_desc
        lines.append(f"- {name}: {mood_desc} (internal: {mood}/10)")
    if not lines:
        return ""
    return (
        "Emotional temperature of people here — reflect this in atmosphere, tension, and behavior "
        "(do not quote these ratings to the player):\n"
        + "\n".join(lines)
    )


def _memory_context_block(state: dict) -> str:
    """Condensed story summary plus last two raw turns for narrator/NPC/mood prompts."""
    summary = state.get("memory_summary") or ""
    hist = state.get("history") or []
    recent = hist[-2:] if len(hist) >= 2 else hist
    summary_block = f"Story so far: {summary}\n\n" if summary else ""
    return summary_block + "\n".join(recent)


def _get_tension_description(state: dict, npc_name: str) -> str:
    """Return the NPC's tension prose for the current milestone stage and tension_mood."""
    characters = state.get("characters") or {}
    npc = characters.get(npc_name)
    if not isinstance(npc, dict):
        return ""
    stages = npc.get("tension_stages")
    if not isinstance(stages, list) or len(stages) == 0:
        return ""

    progress = int(state.get("milestone_progress", 0) or 0)
    idx = progress
    if idx >= len(stages):
        idx = len(stages) - 1

    stage = stages[idx]
    if not isinstance(stage, dict):
        return ""

    tm = state.get("tension_mood")
    if tm not in ("progressing", "stalling"):
        return ""
    desc = stage.get(tm)
    if desc is None:
        return ""
    return str(desc).strip()


def _npc_tension_map(state: dict) -> dict[str, str]:
    """Per-NPC tension line for API clients; only NPCs with non-empty tension descriptions."""
    loc = state.get("location") or ""
    room = (state.get("locations") or {}).get(loc) or {}
    if not isinstance(room, dict):
        return {}
    out: dict[str, str] = {}
    for npc_name in room.get("characters") or []:
        desc = _get_tension_description(state, npc_name)
        if desc:
            out[npc_name] = desc
    return out


# --- State ---
class State(TypedDict):
    message: str
    response: str
    history: list
    narrator: dict
    player: dict
    characters: dict
    location: str
    locations: dict
    rules: dict
    game_title: str
    opening: str
    inventory: list
    turn_count: int
    paused: bool
    milestones: list
    milestone_progress: int
    guide: str
    tension_turns_since_milestone: int
    tension_mood: str
    memory_summary: str
    # Set for one invoke in /chat; stripped before save. Snapshot of world before movement/inventory.
    narrative_turn_snapshot: NotRequired[dict]


def normalize_narrator(narrator: Optional[dict]) -> dict:
    n = dict(narrator or {})
    if not (n.get("prompt") or "").strip():
        logger.warning(
            "Narrator JSON missing non-empty 'prompt'; using default. Add narrator.prompt in games/*.json."
        )
        n["prompt"] = DEFAULT_NARRATOR_PROMPT
    if not n.get("model") or n["model"] == "default":
        n["model"] = DEFAULT_MODEL
    return n


def normalize_characters(characters: Optional[dict]) -> dict:
    out = {}
    for name, npc in (characters or {}).items():
        c = dict(npc)
        if not (c.get("prompt") or "").strip():
            label = str(name).replace("_", " ")
            logger.warning(
                "Character %r missing 'prompt'; using default. Add characters.<id>.prompt in games/*.json.",
                name,
            )
            c["prompt"] = (
                f"You are {label}. Stay in character. Reply in one or two short sentences."
            )
        if not c.get("model") or c["model"] == "default":
            c["model"] = DEFAULT_MODEL
        c.setdefault("mood", 5)
        if not c.get("mood_descriptions"):
            c["mood_descriptions"] = {str(i): f"Mood {i}/10." for i in range(1, 11)}
        out[name] = c
    return out


def normalize_player(player: Optional[dict]) -> dict:
    p = dict(player or {})
    p.setdefault("name", "Adventurer")
    p.setdefault("background", "A traveler in an unknown place.")
    p.setdefault("traits", [])
    return p


def normalize_rules(rules: Optional[dict]) -> dict:
    r = dict(rules or {})
    r.setdefault("win", "")
    r.setdefault("lose", "")
    r.setdefault("trigger_words", {})
    return r


def normalize_locations(locations: Optional[dict]) -> dict:
    """Ensure each location has description, items, and characters lists (engine-safe)."""
    out = {}
    for key, raw in (locations or {}).items():
        if not isinstance(raw, dict):
            continue
        loc = dict(raw)
        if not isinstance(loc.get("description"), str):
            loc["description"] = str(loc.get("description") or "")
        items = loc.get("items")
        loc["items"] = items if isinstance(items, list) else []
        ch = loc.get("characters")
        loc["characters"] = ch if isinstance(ch, list) else []
        out[key] = loc
    return out


def patch_state_engine_fields(state: dict) -> None:
    """Fill missing keys from hand-edited or AI-generated game JSON and old saves."""
    state["narrator"] = normalize_narrator(state.get("narrator"))
    state["characters"] = normalize_characters(state.get("characters"))
    state["player"] = normalize_player(state.get("player"))
    state["rules"] = normalize_rules(state.get("rules"))
    locs = state.get("locations")
    if isinstance(locs, dict):
        state["locations"] = normalize_locations(locs)
    # Legacy saves incremented turn_count once per graph node; reconcile to history length.
    hist = state.get("history") or []
    state["turn_count"] = len(hist)
    if "memory_summary" not in state:
        state["memory_summary"] = ""


def load_game(game_name: str) -> State:
    """Load game from JSON file with full state structure."""
    path = os.path.join(GAMES_DIR, f"{game_name}.json")
    with open(path, "r") as f:
        game = json.load(f)
    if not game.get("locations"):
        raise ValueError("Game JSON must include a non-empty locations object")
    return {
        "message": "",
        "response": "",
        "history": [],
        "narrator": normalize_narrator(game.get("narrator")),
        "player": normalize_player(game.get("player")),
        "characters": normalize_characters(game.get("characters")),
        "location": list(game["locations"].keys())[0],
        "locations": normalize_locations(game["locations"]),
        "rules": normalize_rules(game.get("rules")),
        "game_title": game["title"],
        "opening": game.get("opening", "") or "",
        "inventory": [],
        "turn_count": 0,
        "paused": False,
        "milestones": game.get("milestones", []),
        "milestone_progress": 0,
        "guide": game.get("guide", ""),
        "tension_turns_since_milestone": 0,
        "tension_mood": "progressing",
        "memory_summary": "",
        "_graph_type": game.get("graph_type", "standard"),
    }


def _build_state_from_json(game_data: dict) -> State:
    """Build a game State from parsed game JSON data."""
    if not game_data.get("locations"):
        raise ValueError("Game JSON must include a non-empty locations object")
    return {
        "message": "",
        "response": "",
        "history": [],
        "narrator": normalize_narrator(game_data.get("narrator")),
        "player": normalize_player(game_data.get("player")),
        "characters": normalize_characters(game_data.get("characters")),
        "location": list(game_data["locations"].keys())[0],
        "locations": normalize_locations(game_data["locations"]),
        "rules": normalize_rules(game_data.get("rules")),
        "game_title": game_data.get("title", "Untitled"),
        "opening": game_data.get("opening", "") or "",
        "inventory": [],
        "turn_count": 0,
        "paused": False,
        "milestones": game_data.get("milestones", []),
        "milestone_progress": 0,
        "guide": game_data.get("guide", ""),
        "tension_turns_since_milestone": 0,
        "tension_mood": "progressing",
        "memory_summary": "",
        "_graph_type": game_data.get("graph_type", "standard"),
    }


# --- Nodes ---
def movement_node(state: State) -> State:
    """Detect if the player is trying to move to a new location."""
    location_names = list(state["locations"].keys())
    if len(location_names) <= 1:
        return {}

    model = state["narrator"].get("model", DEFAULT_MODEL)
    try:
        llm = get_llm(model)
    except Exception as e:
        logger.error(f"Failed to get LLM: {e}")
        return {}

    prompt = f"""You are a movement detector for a text adventure game.
The player is currently in: {state["location"]}
Available locations: {", ".join(location_names)}

Player said: {state["message"]}

Is the player trying to move to a different location? If yes, reply with ONLY the exact location key from the list above (same spelling and underscores). If no, reply with ONLY the word STAY."""

    try:
        raw = llm.invoke(prompt)
        token = _normalize_detector_reply(raw)
        if token.lower() == "stay":
            return {}
        for loc in location_names:
            if loc.lower() == token.lower():
                if loc != state["location"]:
                    return {"location": loc}
                return {}
        logger.warning(
            "Movement: reply did not match any location key (got %r); treating as STAY",
            token[:120],
        )
    except Exception as e:
        logger.error(f"Movement node error: {e}")

    return {}


def inventory_node(state: State) -> State:
    """Detect if the player is trying to pick up an item with weight check."""
    location = state["locations"][state["location"]]
    available_items = location.get("items", [])
    if not available_items:
        return {}

    model = state["narrator"].get("model", DEFAULT_MODEL)
    try:
        llm = get_llm(model)
    except Exception as e:
        logger.error(f"Failed to get LLM: {e}")
        return {}

    prompt = f"""You are an item pickup detector for a text adventure game.
Items available in this location: {", ".join(available_items)}
Current inventory weight: {len(state["inventory"])}/{INVENTORY_WEIGHT_LIMIT} items

Player said: {state["message"]}

Is the player trying to pick up or take an item? If yes, reply with ONLY the exact item name from the list above (same spelling). If no, reply with ONLY the word NONE."""

    try:
        raw = llm.invoke(prompt)
        token = _normalize_detector_reply(raw)
        if token.lower() == "none":
            return {}
        for item in available_items:
            if item.lower() == token.lower():
                if len(state["inventory"]) >= INVENTORY_WEIGHT_LIMIT:
                    return {
                        "response": f"Inventory full! You can't carry more than {INVENTORY_WEIGHT_LIMIT} items.",
                    }
                updated_locations = json.loads(json.dumps(state["locations"]))
                room = updated_locations.get(state["location"], {})
                room_items = room.get("items")
                if not isinstance(room_items, list) or item not in room_items:
                    logger.warning("Inventory pickup: item not in room list: %r", item)
                    return {}
                room_items.remove(item)
                room["items"] = room_items
                updated_locations[state["location"]] = room
                new_inventory = state["inventory"] + [item]
                return {
                    "locations": updated_locations,
                    "inventory": new_inventory,
                }
        logger.warning(
            "Inventory: reply did not match any item name (got %r); no pickup",
            token[:120],
        )
    except Exception as e:
        logger.error(f"Inventory node error: {e}")

    return {}


def narrator_node(state: State) -> State:
    location = state["locations"][state["location"]]
    player = state["player"]
    history_text = _memory_context_block(state)
    model = state["narrator"].get("model", DEFAULT_MODEL)
    try:
        llm = get_llm(model)
    except Exception as e:
        logger.error(f"Failed to get LLM: {e}")
        return {
            "response": "[System error: Could not connect to LLM. Try again.]",
        }

    just_arrived = False
    if state["history"]:
        last_turn = state["history"][-1]
        if state["location"] not in last_turn:
            just_arrived = True

    arrival_hint = ""
    if just_arrived:
        arrival_hint = f"\nThe player just arrived at {state['location']}. Describe this new location vividly as they enter it.\n"

    engine_brief = _build_narrative_engine_brief(state)
    engine_block = f"{engine_brief}\n\n" if engine_brief else ""

    milestone_ctx = _format_milestone_context(state)
    milestone_block = f"{milestone_ctx}\n\n" if milestone_ctx else ""

    mood_ctx = _format_mood_context_for_room(state)
    mood_block = f"{mood_ctx}\n\n" if mood_ctx else ""

    narrator_prompt = (state["narrator"].get("prompt") or "").strip() or DEFAULT_NARRATOR_PROMPT
    prompt = f"""{narrator_prompt}

Game: {state["game_title"]}
Player: {player.get("name", "Adventurer")} — {player.get("background", "")}
Current location: {state["location"]} — {location.get("description", "")}
Items here: {", ".join(location.get("items") or []) or "none"}
Player inventory: {", ".join(state["inventory"]) or "empty"}
Characters here: {", ".join(location.get("characters") or []) or "none"}
{milestone_block}{mood_block}{arrival_hint}{engine_block}Context:
{history_text}

Player just said: {state["message"]}

Narrate what happens next:"""

    try:
        narration = llm.invoke(prompt)
        return {"response": narration}
    except Exception as e:
        logger.error(f"Narrator node error: {e}")
        return {
            "response": (
                f"[{_llm_public_error_message(e)}]\n\n"
                f"Location: {location.get('description', '')}"
            ),
        }


def condense_node(state: State) -> State:
    """Merge recent exchanges into memory_summary; one LLM call (narrator model)."""
    history = state.get("history") or []
    if not history:
        return {}

    memory_summary = (state.get("memory_summary") or "").strip()
    summary_placeholder = (
        memory_summary
        if memory_summary
        else "No summary yet — this is the beginning of the story."
    )

    recent_raw = history[-3:]
    recent_block = "\n\n".join(recent_raw)
    current_turn = f"Player: {state['message']}\n{state['response']}"

    model = state["narrator"].get("model", DEFAULT_MODEL)
    try:
        llm = get_llm(model)
    except Exception as e:
        logger.error(f"Condense node: could not get LLM: {e}")
        return {}

    prompt = f"""You are a story memory manager. Your job is to maintain a concise summary of everything important that has happened in this story.

Current summary:
{summary_placeholder}

Recent raw turns (last 3 completed exchanges):
{recent_block}

New events to incorporate:
{current_turn}

Update the summary to include any important new information from the new events. Rules:
- Keep the summary under 100 words
- Focus on: key facts, relationship developments, promises made, things characters revealed, emotional shifts, milestone moments
- Drop: scenery descriptions, small talk, redundant details
- Write in past tense, third person
- If the summary is getting long, compress older details to make room for new ones

Updated summary:

"""

    try:
        raw = llm.invoke(prompt)
        text = (raw or "").strip() if isinstance(raw, str) else str(raw).strip()
        if not text:
            return {}
        return {"memory_summary": text}
    except Exception as e:
        logger.error(f"Condense node error: {e}")
        return {}


def mood_node(state: State) -> State:
    characters = state["characters"]
    updated_characters = dict(characters)

    room = state["locations"].get(state["location"], {}) or {}
    npcs_here = [
        name
        for name in (room.get("characters") or [])
        if name in characters
    ]

    if not npcs_here:
        return {}

    # Parallelize mood updates
    def update_mood(npc_name: str, npc: dict) -> tuple:
        current_mood = npc.get("mood", 5)
        model = npc.get("model", DEFAULT_MODEL)
        try:
            llm = get_llm(model)
        except Exception as e:
            logger.error(f"Failed to get LLM for {npc_name}: {e}")
            return npc_name, npc

        context_text = _memory_context_block(state)
        prompt = f"""You are evaluating how a character's mood should change after a conversation exchange.

Character: {npc_name} (current mood: {current_mood}/10)
Player action: {state["message"]}
Context:
{context_text}

Based on the player's action, should {npc_name}'s mood go up, down, or stay the same?
Reply with ONLY one word: UP, DOWN, or SAME."""

        try:
            result = llm.invoke(prompt).strip().upper()
            if "UP" in result:
                new_mood = min(10, current_mood + 1)
            elif "DOWN" in result:
                new_mood = max(1, current_mood - 1)
            else:
                new_mood = current_mood

            updated_npc = dict(npc)
            updated_npc["mood"] = new_mood
            return npc_name, updated_npc
        except Exception as e:
            logger.error(f"Mood update error for {npc_name}: {e}")
            return npc_name, npc

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(update_mood, name, characters[name])
            for name in npcs_here
        ]
        for future in as_completed(futures):
            name, updated_char = future.result()
            updated_characters[name] = updated_char

    return {"characters": updated_characters}


def npc_node(state: State) -> State:
    location = state["locations"][state["location"]]
    npcs_here = location.get("characters") or []

    if not npcs_here:
        return {}

    history_text = _memory_context_block(state)
    full_response = state["response"]
    # Use narrator beat if available (standard graph), fall back to last history entry (social graph)
    narrator_beat = (state.get("response") or "").strip()
    if not narrator_beat and state["history"]:
        narrator_beat = state["history"][-1]

    def get_npc_response(npc_name: str) -> Optional[str]:
        if npc_name not in state["characters"]:
            return None

        npc = state["characters"][npc_name]
        mood = npc.get("mood", 5)
        mood_descriptions = npc.get("mood_descriptions", {})
        mood_desc = mood_descriptions.get(str(mood), f"Mood level {mood}/10.")
        tension_desc = _get_tension_description(state, npc_name)
        if tension_desc:
            mood_desc = tension_desc
        model = npc.get("model", DEFAULT_MODEL)
        try:
            llm = get_llm(model)
        except Exception as e:
            logger.error(f"Failed to get LLM for {npc_name}: {e}")
            return None

        player = state["player"]
        npc_prompt = (npc.get("prompt") or "").strip() or (
            f"You are {npc_name}. Stay in character."
        )
        milestone_ctx = _format_milestone_context(state)
        milestone_block = f"{milestone_ctx}\n\n" if milestone_ctx else ""
        guide_block = ""
        if (state.get("guide") or "") == npc_name and (state.get("milestones") or []):
            guide_block = (
                "You are this story's guide. If the conversation stalls or drifts, gently nudge "
                "toward the current milestone above — stay in character.\n\n"
            )
        prompt = f"""{npc_prompt}

{milestone_block}{guide_block}You are speaking to {player.get("name", "Adventurer")}. {player.get("background", "")}.
Current mood: {mood_desc}

What the narrator just established in this scene (stay consistent; react naturally):
{narrator_beat}

Context:
{history_text}

{player.get("name", "Adventurer")} just said: {state["message"]}

Respond as {npc_name} in one or two short sentences:"""

        try:
            npc_response = llm.invoke(prompt)
            mood_indicator = f"[{npc_name} mood: {mood}/10]"
            return f"{npc_name.title()}: {npc_response.strip()}\n{mood_indicator}"
        except Exception as e:
            logger.error(f"NPC response error for {npc_name}: {e}")
            return None

    responses = []
    for npc_name in npcs_here:
        response = get_npc_response(npc_name)
        if response:
            responses.append(response)

    if responses:
        full_response = f"{full_response}\n\n" + "\n\n".join(responses)

    return {"response": full_response}


def milestone_node(state: State) -> State:
    """Check milestone progression via choice selection. No LLM needed."""
    milestones = state.get("milestones") or []
    progress = state.get("milestone_progress", 0)

    # Nothing to check if no milestones or all complete
    if not milestones or progress >= len(milestones):
        return {}

    current_milestone = milestones[progress]
    player_message = state["message"].strip().lower()

    # Check if the player's message contains the current milestone
    if current_milestone.lower() in player_message:
        new_progress = progress + 1
        milestone_hint = f"[Milestone achieved: {current_milestone}]"
        if new_progress < len(milestones):
            milestone_hint += f" Next milestone: {milestones[new_progress]}"
        else:
            milestone_hint += " All milestones complete!"
        return {
            "milestone_progress": new_progress,
            "response": milestone_hint,
        }

    # Check if the player tried to pick a future milestone
    future_milestones = milestones[progress + 1:]
    for future in future_milestones:
        if future.lower() in player_message:
            return {
                "response": f"[Milestone blocked: you must first: {current_milestone}]",
            }

    # Normal message, not a milestone choice
    return {}


def guide_arrival_node(state: State) -> State:
    """If the guide NPC isn't in the current room, move them here."""
    guide_name = state.get("guide") or ""
    if not guide_name:
        return {}

    # Check if guide exists in characters
    if guide_name not in state["characters"]:
        return {}

    # Check if guide is already in the current room
    current_room = state["locations"].get(state["location"], {})
    room_characters = current_room.get("characters") or []
    if guide_name in room_characters:
        return {}

    # Move the guide: remove from old room, add to current room
    updated_locations = json.loads(json.dumps(state["locations"]))

    # Remove guide from wherever they are now
    for loc_key, loc_data in updated_locations.items():
        chars = loc_data.get("characters") or []
        if guide_name in chars:
            chars.remove(guide_name)
            loc_data["characters"] = chars

    # Add guide to current room
    current = updated_locations[state["location"]]
    chars = current.get("characters") or []
    chars.append(guide_name)
    current["characters"] = chars

    return {
        "locations": updated_locations,
        "response": f"[{guide_name.title()} arrives]",
    }


def tension_node(state: State) -> State:
    """Update stall tension from turns since last milestone. No LLM — pure engine logic."""
    milestones = state.get("milestones") or []
    if not milestones:
        return {}

    response = state.get("response") or ""
    if "[Milestone achieved" in response:
        return {
            "tension_turns_since_milestone": 0,
            "tension_mood": "progressing",
        }

    prev = int(state.get("tension_turns_since_milestone", 0) or 0)
    new_count = prev + 1

    room = (state.get("locations") or {}).get(state.get("location") or "", {}) or {}
    names = room.get("characters") or []
    characters = state.get("characters") or {}

    thresholds: list[int] = []
    for name in names:
        npc = characters.get(name)
        if not isinstance(npc, dict):
            continue
        raw = npc.get("stall_threshold")
        if raw is None:
            continue
        try:
            st = int(raw)
        except (TypeError, ValueError):
            continue
        if st <= 0:
            continue
        thresholds.append(st)

    if thresholds:
        lowest = min(thresholds)
        new_mood = "stalling" if new_count >= lowest else "progressing"
    else:
        new_mood = "progressing"

    return {
        "tension_turns_since_milestone": new_count,
        "tension_mood": new_mood,
    }


def memory_node(state: State) -> State:
    turn = f"Player: {state['message']}\n{state['response']}"
    new_history = add_to_history(list(state["history"]), turn, HISTORY_LIMIT)
    # One completed exchange == one history entry; keep counter aligned.
    return {"history": new_history, "turn_count": len(new_history)}


def rules_node(state: State) -> State:
    """Check win/lose conditions and trigger words with validation."""
    rules = state["rules"]
    message_lower = state["message"].lower()
    response = state["response"]

    # Check trigger words first
    for trigger, result_text in rules.get("trigger_words", {}).items():
        if trigger.lower() in message_lower:
            response = f"{response}\n\n{result_text}"
            return {"response": response}

    # Check win/lose conditions
    win_cond = rules.get("win", "")
    lose_cond = rules.get("lose", "")
    if not win_cond and not lose_cond:
        return {}

    # If milestones exist, block WIN until all are complete
    milestones = state.get("milestones") or []
    progress = state.get("milestone_progress", 0)
    milestones_incomplete = milestones and progress < len(milestones)

    try:
        model = state["narrator"].get("model", DEFAULT_MODEL)
        llm = get_llm(model)
    except Exception as e:
        logger.error(f"Failed to get LLM: {e}")
        return {}

    history_text = "\n".join(state["history"][-6:])
    prompt = f"""You are a strict game rules judge. Use only what is stated in the recent history and the latest exchange.

Win condition (must be clearly achieved in the story, not merely possible): {win_cond}
Lose condition (must be clearly achieved in the story): {lose_cond}

Recent history:
{history_text}

Latest exchange:
Player: {state["message"]}
Response: {state["response"]}

Rules:
- Reply WIN only if the win condition is explicitly established in the narrative (facts or dialogue), not guessed.
- Reply LOSE only if the lose condition is explicitly established.
- If either condition is ambiguous, still in progress, or only hinted, reply CONTINUE.
- Reply with ONLY one word: WIN, LOSE, or CONTINUE."""

    try:
        result = llm.invoke(prompt).strip().upper()
    except Exception as e:
        logger.error(f"Rules check error: {e}")
        return {}

    if "WIN" in result and not milestones_incomplete:
        response = f"{response}\n\n🏆 [GAME OVER — YOU WIN! {win_cond}]"
    elif "LOSE" in result:
        response = f"{response}\n\n💀 [GAME OVER — YOU LOSE! {lose_cond}]"

    return {"response": response}


# --- Graph routing helpers (conditional edges) ---
def _routing_current_room(state: State) -> dict:
    loc = state.get("location") or ""
    locs = state.get("locations") or {}
    room = locs.get(loc)
    return room if isinstance(room, dict) else {}


def route_graph_entry(state: State) -> str:
    if len(state["locations"]) <= 1:
        return "inventory"
    return "movement"


def route_after_movement(state: State) -> str:
    room = _routing_current_room(state)
    items = room.get("items") or []
    if not items:
        return "narrator"
    return "inventory"


def route_after_narrator(state: State) -> str:
    room = _routing_current_room(state)
    npcs = room.get("characters") or []
    if not npcs:
        return "memory"
    return "mood"


def route_after_memory(state: State) -> str:
    rules = state.get("rules") or {}
    win = (rules.get("win") or "").strip()
    lose = (rules.get("lose") or "").strip()
    tw = rules.get("trigger_words") or {}
    if not win and not lose and not tw:
        return END
    return "rules"


def route_social_entry(state: State) -> str:
    """Social graph entry: skip to guide_arrival if only one location, else movement."""
    if len(state["locations"]) <= 1:
        return "guide_arrival"
    return "movement"


NODE_REGISTRY = {
    "movement": movement_node,
    "inventory": inventory_node,
    "narrator": narrator_node,
    "mood": mood_node,
    "npc": npc_node,
    "condense": condense_node,
    "memory": memory_node,
    "rules": rules_node,
    "milestone": milestone_node,
    "guide_arrival": guide_arrival_node,
    "tension": tension_node,
}


ROUTER_REGISTRY = {
    "route_graph_entry": route_graph_entry,
    "route_after_movement": route_after_movement,
    "route_after_narrator": route_after_narrator,
    "route_after_memory": route_after_memory,
    "route_social_entry": route_social_entry,
}


def _normalize_router_mapping(mapping: dict) -> dict:
    """Replace '__end__' string keys/values with LangGraph END for JSON definitions."""
    out: dict = {}
    for k, v in mapping.items():
        nk = END if k == "__end__" else k
        nv = END if v == "__end__" else v
        out[nk] = nv
    return out


def build_graph_from_json(definition: dict):
    """Build a compiled StateGraph from a JSON-style pipeline definition."""
    g = StateGraph(State)

    for name in definition["nodes"]:
        g.add_node(name, NODE_REGISTRY[name])

    entry = definition["entry_point"]
    entry_router = ROUTER_REGISTRY[entry["router"]]
    entry_mapping = _normalize_router_mapping(entry["mapping"])
    g.set_conditional_entry_point(entry_router, entry_mapping)

    for edge in definition["edges"]:
        to_node = END if edge["to"] == "__end__" else edge["to"]
        g.add_edge(edge["from"], to_node)

    for spec in definition["conditional_edges"]:
        router_fn = ROUTER_REGISTRY[spec["router"]]
        proc_map = _normalize_router_mapping(spec["mapping"])
        g.add_conditional_edges(spec["from"], router_fn, proc_map)

    return g.compile()


def _load_graph_definitions() -> dict:
    """Load compiled LangGraph pipelines from ``graphs/*.json``."""
    registry: dict = {}
    if not GRAPHS_DIR.exists():
        logger.warning("GRAPHS_DIR does not exist: %s", GRAPHS_DIR)
        return registry

    paths = sorted(GRAPHS_DIR.glob("*.json"))
    if not paths:
        logger.warning("No graph JSON files found in %s", GRAPHS_DIR)
        return registry

    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                definition = json.load(f)
            name = definition.get("name")
            if not name:
                logger.warning("Graph file %s has no 'name' field; skipping", path)
                continue
            if name in registry:
                logger.warning(
                    "Duplicate graph name %r in %s; overwriting earlier entry",
                    name,
                    path.name,
                )
            registry[name] = build_graph_from_json(definition)
            logger.info("Loaded graph %r from %s", name, path.name)
        except Exception as e:
            logger.error("Failed to load graph from %s: %s", path, e)

    return registry


GRAPH_REGISTRY = _load_graph_definitions()


def get_compiled_graph(graph_type: str):
    """Look up a compiled graph by name; fall back to 'standard' if unknown."""
    return GRAPH_REGISTRY.get(graph_type, GRAPH_REGISTRY["standard"])


def _safe_graph_basename(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    return all(c.isalnum() or c in "_-" for c in name)


def _validate_graph_definition(
    definition: dict, url_name: Optional[str] = None
) -> tuple[bool, str]:
    """Return (True, '') if valid, else (False, error message)."""
    if not isinstance(definition, dict):
        return False, "Body must be a JSON object"

    name = definition.get("name")
    if not name or not isinstance(name, str):
        return False, "Field 'name' is required and must be a string"
    if not _safe_graph_basename(name):
        return False, "Invalid 'name': use only letters, numbers, underscores, and hyphens"

    if url_name is not None and name != url_name:
        return False, f"Field 'name' must match URL ({url_name!r})"

    nodes = definition.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return False, "'nodes' must be a non-empty list of strings"
    if not all(isinstance(n, str) for n in nodes):
        return False, "Each entry in 'nodes' must be a string"
    node_set = set(nodes)

    for n in nodes:
        if n not in NODE_REGISTRY:
            return False, f"Unknown node type: {n!r}"

    entry = definition.get("entry_point")
    if not isinstance(entry, dict):
        return False, "'entry_point' must be an object"
    entry_router = entry.get("router")
    if not isinstance(entry_router, str) or entry_router not in ROUTER_REGISTRY:
        return False, f"Unknown entry_point router: {entry_router!r}"
    if not isinstance(entry.get("mapping"), dict):
        return False, "'entry_point.mapping' must be an object"

    edges = definition.get("edges")
    if not isinstance(edges, list):
        return False, "'edges' must be a list"
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            return False, f"edges[{i}] must be an object"
        from_n = edge.get("from")
        to_n = edge.get("to")
        if from_n not in node_set:
            return False, f"edges[{i}].from {from_n!r} is not listed in 'nodes'"
        if to_n != "__end__" and to_n not in node_set:
            return False, f"edges[{i}].to {to_n!r} is not listed in 'nodes' (use '__end__' for END)"

    cond_edges = definition.get("conditional_edges")
    if not isinstance(cond_edges, list):
        return False, "'conditional_edges' must be a list"
    for i, ce in enumerate(cond_edges):
        if not isinstance(ce, dict):
            return False, f"conditional_edges[{i}] must be an object"
        r = ce.get("router")
        if not isinstance(r, str) or r not in ROUTER_REGISTRY:
            return False, f"Unknown router in conditional_edges[{i}]: {r!r}"
        if not isinstance(ce.get("mapping"), dict):
            return False, f"conditional_edges[{i}].mapping must be an object"

    try:
        build_graph_from_json(definition)
    except Exception as e:
        logger.warning("build_graph_from_json failed during validation: %s", e)
        return False, f"Invalid graph structure: {e}"

    return True, ""


# --- Game state in memory (keyed by per-adventure session_id string) ---
active_games = {}

_adventure_locks_guard = threading.Lock()
_adventure_locks: dict[str, threading.Lock] = {}
CHAT_LOCK_TIMEOUT_S = 60


def _get_adventure_lock(session_id: str) -> threading.Lock:
    with _adventure_locks_guard:
        lock = _adventure_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _adventure_locks[session_id] = lock
        return lock


# --- SQLite persistence for adventures ---
def _serialize_state(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False)


def upsert_save_slot_db(conn, adventure_id: int, slot: int, state: dict) -> None:
    conn.execute(
        """
        INSERT INTO save_slots (adventure_id, slot, data, saved_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(adventure_id, slot) DO UPDATE SET
            data = excluded.data,
            saved_at = excluded.saved_at
        """,
        (adventure_id, slot, _serialize_state(dict(state))),
    )


def load_save_slot_db(conn, adventure_id: int, slot: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT data FROM save_slots WHERE adventure_id = ? AND slot = ?",
        (adventure_id, slot),
    ).fetchone()
    if not row:
        return None
    data = json.loads(row["data"])
    if "opening" not in data:
        data["opening"] = ""
    return data


def load_latest_save_slot_db(conn, adventure_id: int) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT data FROM save_slots WHERE adventure_id = ?
        ORDER BY saved_at DESC LIMIT 1
        """,
        (adventure_id,),
    ).fetchone()
    if not row:
        return None
    data = json.loads(row["data"])
    if "opening" not in data:
        data["opening"] = ""
    return data


def get_save_slots_db(conn, adventure_id: int) -> list:
    rows = conn.execute(
        """
        SELECT slot, data, saved_at FROM save_slots
        WHERE adventure_id = ? ORDER BY slot ASC
        """,
        (adventure_id,),
    ).fetchall()
    slots = []
    for row in rows:
        try:
            data = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            continue
        slots.append(
            {
                "slot": row["slot"],
                "timestamp": row["saved_at"],
                "location": data.get("location", "unknown"),
                "turns": len(data.get("history", [])),
            }
        )
    return slots


def fetch_owned_adventure(conn, adventure_id: int, user_id: int):
    return conn.execute(
        "SELECT * FROM adventures WHERE id = ? AND user_id = ?",
        (adventure_id, user_id),
    ).fetchone()


def ensure_adventure_in_memory(conn, row) -> Optional[tuple]:
    """Return (http_status, err_dict) if error, else None."""
    session_id = row["session_id"]
    if not session_id:
        return 400, {"error": "Adventure has no session"}

    if session_id in active_games:
        patch_state_engine_fields(active_games[session_id])
        return None

    aid = row["id"]
    slot = row["active_slot"]
    saved = load_save_slot_db(conn, aid, slot)
    if not saved:
        saved = load_latest_save_slot_db(conn, aid)
    if saved:
        patch_state_engine_fields(saved)
        active_games[session_id] = saved
        return None

    gcid = row["game_content_id"]
    if gcid is not None:
        gc_row = conn.execute(
            "SELECT game_json FROM game_content WHERE id = ?", (gcid,)
        ).fetchone()
        if not gc_row:
            return 404, {"error": "Game not found"}
        try:
            game_data = json.loads(gc_row["game_json"])
            state = _build_state_from_json(game_data)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.error("Failed to reload game_content %s: %s", gcid, e)
            return 404, {"error": "Invalid story data"}
        active_games[session_id] = state
        return None

    game_file_key = (row["game_file"] or "").strip()
    if not game_file_key:
        return 404, {"error": "Game not found"}

    try:
        state = load_game(game_file_key)
    except Exception as e:
        logger.error("Failed to reload game %s: %s", game_file_key, e)
        return 404, {"error": f"Game not found: {game_file_key}"}

    active_games[session_id] = state
    return None


def build_opening_message(state: dict) -> str:
    room = state["locations"][state["location"]]
    room_desc = room.get("description", "") if isinstance(room, dict) else ""
    intro = (state.get("opening") or "").strip()
    first_lines = [
        f"{name.title()}: {char['first_line']}"
        for name, char in state["characters"].items()
        if "first_line" in char
    ]
    blocks = []
    if intro:
        blocks.append(intro)
    blocks.append(room_desc)
    response = "\n\n".join(blocks)
    if first_lines:
        response = f"{response}\n\n" + "\n".join(first_lines)
    return response


# --- Flask routes ---


@app.route("/graphs", methods=["GET"])
def list_graph_definitions():
    """List graph metadata (name, description, node_count) from ``graphs/*.json``."""
    if not GRAPHS_DIR.exists():
        return jsonify({"graphs": []})

    out = []
    for path in sorted(GRAPHS_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Skipping %s: %s", path, e)
            continue
        nodes = data.get("nodes")
        ncount = len(nodes) if isinstance(nodes, list) else 0
        out.append(
            {
                "name": data.get("name") or path.stem,
                "description": (data.get("description") or "") if isinstance(data.get("description"), str) else "",
                "node_count": ncount,
            }
        )
    return jsonify(out)


@app.route("/graphs/<name>", methods=["GET"])
def get_graph_definition(name: str):
    if not _safe_graph_basename(name):
        return jsonify({"error": "Invalid graph name"}), 400
    path = GRAPHS_DIR / f"{name}.json"
    if not path.is_file():
        return jsonify({"error": "Graph not found"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(data)


@app.route("/graphs/<name>", methods=["PUT"])
def put_graph_definition(name: str):
    if not _safe_graph_basename(name):
        return jsonify({"error": "Invalid graph name"}), 400
    definition = request.get_json(silent=True)
    if not isinstance(definition, dict):
        return jsonify({"error": "JSON body required"}), 400

    ok, err = _validate_graph_definition(definition, url_name=name)
    if not ok:
        return jsonify({"error": err}), 400

    path = GRAPHS_DIR / f"{name}.json"
    try:
        GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(definition, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        return jsonify({"error": str(e)}), 500

    try:
        GRAPH_REGISTRY[name] = build_graph_from_json(definition)
    except Exception as e:
        logger.exception("Failed to compile graph after save")
        return jsonify({"error": f"Saved file but failed to compile: {e}"}), 500

    logger.info("Updated graph %r at %s", name, path.name)
    return jsonify({"ok": True, "name": name}), 200


@app.route("/graphs", methods=["POST"])
def post_graph_definition():
    definition = request.get_json(silent=True)
    if not isinstance(definition, dict):
        return jsonify({"error": "JSON body required"}), 400

    ok, err = _validate_graph_definition(definition, url_name=None)
    if not ok:
        return jsonify({"error": err}), 400

    name = definition["name"]
    path = GRAPHS_DIR / f"{name}.json"
    if path.is_file():
        return jsonify({"error": f"Graph {name!r} already exists"}), 409

    try:
        GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(definition, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        return jsonify({"error": str(e)}), 500

    try:
        GRAPH_REGISTRY[name] = build_graph_from_json(definition)
    except Exception as e:
        logger.exception("Failed to compile graph after create")
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return jsonify({"error": f"Failed to compile graph: {e}"}), 500

    logger.info("Created graph %r at %s", name, path.name)
    return jsonify({"ok": True, "name": name}), 200


@app.route("/graphs/<name>", methods=["DELETE"])
def delete_graph_definition(name: str):
    if not _safe_graph_basename(name):
        return jsonify({"error": "Invalid graph name"}), 400
    if name == "standard":
        return jsonify({"error": "Cannot delete the 'standard' graph"}), 403

    path = GRAPHS_DIR / f"{name}.json"
    if not path.is_file():
        return jsonify({"error": "Graph not found"}), 404

    try:
        path.unlink()
    except OSError as e:
        return jsonify({"error": str(e)}), 500

    GRAPH_REGISTRY.pop(name, None)
    logger.info("Deleted graph %r (%s)", name, path.name)
    return jsonify({"ok": True, "name": name}), 200


@app.route("/graph-registry", methods=["GET"])
def graph_registry_keys():
    return jsonify(
        {
            "nodes": sorted(NODE_REGISTRY.keys()),
            "routers": sorted(ROUTER_REGISTRY.keys()),
        }
    )


@app.route("/games", methods=["GET"])
def list_games():
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, title, description, genre, game_json, catalog_file_stem
            FROM game_content
            WHERE is_global = 1 OR is_public = 1
            ORDER BY is_global DESC, play_count DESC, title ASC
            """
        ).fetchall()
    finally:
        conn.close()

    games = []
    for row in rows:
        try:
            data = json.loads(row["game_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        stem = None
        if "catalog_file_stem" in row.keys():
            stem = (row["catalog_file_stem"] or "").strip() or None
        slug = stem or data.get("title", "").lower().replace(" ", "_")
        games.append(
            {
                "id": row["id"],
                "file": slug,
                "title": row["title"],
                "description": row["description"] or "",
                "genre": row["genre"] or "",
                "opening": data.get("opening", ""),
                "graph_type": data.get("graph_type", "standard"),
            }
        )
    return jsonify({"games": games})


# --- Auth (no login_required) ---
@app.route("/register", methods=["POST"])
def register_user():
    data = request.get_json(silent=True) or {}
    uid = (data.get("uid") or "").strip()
    password = data.get("password") or ""
    if not uid:
        return jsonify({"error": "uid is required"}), 400
    if len(password) < 4:
        return jsonify({"error": "password must be at least 4 characters"}), 400

    conn = get_db()
    try:
        try:
            conn.execute(
                "INSERT INTO users (uid, password_hash) VALUES (?, ?)",
                (uid, hash_password(password)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return jsonify({"error": "Username already taken"}), 409
        row = conn.execute("SELECT id FROM users WHERE uid = ?", (uid,)).fetchone()
    finally:
        conn.close()

    session["user_id"] = row["id"]
    return jsonify({"uid": uid}), 201


@app.route("/login", methods=["POST"])
def login_user():
    data = request.get_json(silent=True) or {}
    uid = (data.get("uid") or "").strip()
    password = data.get("password") or ""

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE uid = ?", (uid,)
        ).fetchone()
    finally:
        conn.close()

    if not row or not check_password(password, row["password_hash"]):
        return jsonify({"error": "Invalid uid or password"}), 401

    session["user_id"] = row["id"]
    return jsonify({"uid": uid})


@app.route("/logout", methods=["POST"])
def logout_user():
    session.clear()
    return jsonify({"ok": True})


@app.route("/me", methods=["GET"])
@login_required
def me():
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, uid FROM users WHERE id = ?", (g.user_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"uid": row["uid"], "user_id": row["id"]})


# --- Adventures ---
@app.route("/adventures", methods=["GET"])
@login_required
def list_adventures():
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, game_file, game_content_id, name, session_id, created_at, last_played
            FROM adventures
            WHERE user_id = ?
            ORDER BY last_played DESC NULLS LAST, created_at DESC
            """,
            (g.user_id,),
        ).fetchall()
    finally:
        conn.close()

    adventures = []
    for r in rows:
        adv = {
            "id": r["id"],
            "game_file": r["game_file"],
            "name": r["name"],
            "session_id": r["session_id"],
            "created_at": r["created_at"],
            "last_played": r["last_played"],
        }
        if "game_content_id" in r.keys():
            adv["game_content_id"] = r["game_content_id"]
        adventures.append(adv)
    return jsonify({"adventures": adventures})


@app.route("/adventures", methods=["POST"])
@login_required
def create_adventure():
    data = request.get_json(silent=True) or {}
    game_content_id = data.get("game_content_id")
    game_file = (data.get("game_file") or "").strip().replace(".json", "")

    conn = get_db()
    try:
        if game_content_id is not None:
            try:
                gcid = int(game_content_id)
            except (TypeError, ValueError):
                return jsonify({"error": "invalid game_content_id"}), 400

            gc_row = conn.execute(
                "SELECT * FROM game_content WHERE id = ?", (gcid,)
            ).fetchone()
            if not gc_row:
                return jsonify({"error": "Story not found"}), 404

            if (
                not gc_row["is_global"]
                and not gc_row["is_public"]
                and gc_row["user_id"] != g.user_id
            ):
                return jsonify({"error": "Story not found"}), 404

            try:
                game_data = json.loads(gc_row["game_json"])
            except (json.JSONDecodeError, TypeError):
                return jsonify({"error": "Invalid story data"}), 400

            name = (data.get("name") or "").strip() or gc_row["title"]

            if gc_row["user_id"] != g.user_id:
                stem = None
                if "catalog_file_stem" in gc_row.keys() and gc_row["catalog_file_stem"]:
                    stem = str(gc_row["catalog_file_stem"]).strip() or None
                cur_gc = conn.execute(
                    """
                    INSERT INTO game_content (user_id, title, description, genre, game_json,
                        source_id, original_author_id, is_public, is_global, catalog_file_stem)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                    """,
                    (
                        g.user_id,
                        gc_row["title"],
                        gc_row["description"],
                        gc_row["genre"],
                        gc_row["game_json"],
                        gcid,
                        gc_row["original_author_id"] or gc_row["user_id"],
                        stem,
                    ),
                )
                user_gc_id = cur_gc.lastrowid
                conn.execute(
                    "UPDATE game_content SET play_count = play_count + 1 WHERE id = ?",
                    (gcid,),
                )
            else:
                user_gc_id = gcid

            state = _build_state_from_json(game_data)

        elif game_file:
            game_path = os.path.join(GAMES_DIR, f"{game_file}.json")
            if not os.path.isfile(game_path):
                return jsonify({"error": f"Game not found: {game_file}"}), 404

            try:
                state = load_game(game_file)
            except Exception as e:
                logger.error("load_game %s: %s", game_file, e)
                return jsonify({"error": f"Invalid game: {game_file}"}), 400

            name = (data.get("name") or "").strip() or state.get(
                "game_title", game_file
            )
            user_gc_id = None
        else:
            return jsonify({"error": "game_content_id or game_file is required"}), 400

        session_key = f"adv_{secrets.token_hex(16)}"
        active_games[session_key] = state
        opening = build_opening_message(state)

        cur = conn.execute(
            """
            INSERT INTO adventures (user_id, game_file, name, session_id, game_content_id, last_played)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (g.user_id, game_file or "", name, session_key, user_gc_id),
        )
        adventure_id = cur.lastrowid
        upsert_save_slot_db(conn, adventure_id, 0, state)
        conn.commit()
    finally:
        conn.close()

    adventure = {
        "id": adventure_id,
        "game_file": game_file,
        "name": name,
        "session_id": session_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_played": datetime.now(timezone.utc).isoformat(),
    }
    return jsonify({"adventure": adventure, "response": opening})


@app.route("/adventures/<int:adventure_id>", methods=["DELETE"])
@login_required
def delete_adventure(adventure_id: int):
    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, adventure_id, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404

        sid = row["session_id"]
        if sid and sid in active_games:
            del active_games[sid]
        if sid:
            with _adventure_locks_guard:
                _adventure_locks.pop(sid, None)

        conn.execute("DELETE FROM save_slots WHERE adventure_id = ?", (adventure_id,))
        conn.execute(
            "DELETE FROM adventures WHERE id = ? AND user_id = ?",
            (adventure_id, g.user_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@app.route("/game-content", methods=["GET"])
@login_required
def list_my_game_content():
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT gc.id, gc.title, gc.description, gc.genre, gc.is_public,
                   gc.source_id, gc.play_count, gc.created_at, gc.updated_at,
                   gc.game_json,
                   u.uid as original_author_name
            FROM game_content gc
            LEFT JOIN users u ON gc.original_author_id = u.id
            WHERE gc.user_id = ?
            ORDER BY gc.updated_at DESC
            """,
            (g.user_id,),
        ).fetchall()
    finally:
        conn.close()

    stories = []
    for r in rows:
        try:
            parsed = json.loads(r["game_json"])
            graph_type = parsed.get("graph_type", "standard")
        except (json.JSONDecodeError, TypeError):
            graph_type = "standard"
        stories.append(
            {
                "id": r["id"],
                "title": r["title"],
                "description": r["description"],
                "genre": r["genre"],
                "is_public": bool(r["is_public"]),
                "source_id": r["source_id"],
                "play_count": r["play_count"],
                "original_author": r["original_author_name"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "graph_type": graph_type,
            }
        )
    return jsonify({"stories": stories})


@app.route("/game-content/<int:story_id>", methods=["GET"])
@login_required
def get_game_content(story_id: int):
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT gc.*, u.uid as original_author_name
            FROM game_content gc
            LEFT JOIN users u ON gc.original_author_id = u.id
            WHERE gc.id = ? AND gc.user_id = ?
            """,
            (story_id, g.user_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"error": "Story not found"}), 404
    return jsonify({
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "genre": row["genre"],
        "game_json": row["game_json"],
        "is_public": bool(row["is_public"]),
        "source_id": row["source_id"],
        "play_count": row["play_count"],
        "original_author": row["original_author_name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    })


@app.route("/game-content", methods=["POST"])
@login_required
def create_game_content():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    game_json_raw = data.get("game_json")
    if not game_json_raw:
        return jsonify({"error": "game_json is required"}), 400

    if isinstance(game_json_raw, str):
        try:
            game_data = json.loads(game_json_raw)
        except json.JSONDecodeError as e:
            return jsonify({"error": f"Invalid JSON: {e}"}), 400
    elif isinstance(game_json_raw, dict):
        game_data = game_json_raw
    else:
        return jsonify({"error": "game_json must be a JSON string or object"}), 400

    locs = game_data.get("locations")
    if not isinstance(locs, dict) or not locs:
        return jsonify({"error": "Game JSON must include a non-empty 'locations' object"}), 400
    game_data["locations"] = normalize_locations(locs)
    if not game_data["locations"]:
        return jsonify(
            {"error": "locations must contain at least one valid room object"}
        ), 400
    if not game_data.get("title"):
        game_data["title"] = title

    description = (
        (data.get("description") or "").strip() or game_data.get("description", "")
    )
    genre = (data.get("genre") or "").strip() or game_data.get("genre", "")

    verrors = _validation_errors_for_game(game_data)
    if verrors:
        return jsonify(
            {"error": "Game JSON failed validation", "details": verrors[:20]}
        ), 400

    conn = get_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO game_content (user_id, title, description, genre, game_json,
                original_author_id, is_public, is_global)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (
                g.user_id,
                title,
                description,
                genre,
                json.dumps(game_data, ensure_ascii=False),
                g.user_id,
            ),
        )
        conn.commit()
        story_id = cur.lastrowid
    finally:
        conn.close()

    return jsonify({"id": story_id, "title": title}), 201


@app.route("/game-content/<int:story_id>", methods=["PUT"])
@login_required
def update_game_content(story_id: int):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM game_content WHERE id = ? AND user_id = ?",
            (story_id, g.user_id),
        ).fetchone()
        if not row:
            return jsonify({"error": "Story not found"}), 404

        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip() or row["title"]
        description = (
            data["description"] if "description" in data else row["description"]
        )
        genre = data["genre"] if "genre" in data else row["genre"]

        game_json_raw = data.get("game_json")
        if game_json_raw is not None:
            if isinstance(game_json_raw, str):
                try:
                    game_data = json.loads(game_json_raw)
                except json.JSONDecodeError as e:
                    return jsonify({"error": f"Invalid JSON: {e}"}), 400
            elif isinstance(game_json_raw, dict):
                game_data = game_json_raw
            else:
                return jsonify(
                    {"error": "game_json must be a JSON string or object"}
                ), 400

            locs = game_data.get("locations")
            if not isinstance(locs, dict) or not locs:
                return jsonify(
                    {"error": "Game JSON must include a non-empty 'locations' object"}
                ), 400
            game_data["locations"] = normalize_locations(locs)
            if not game_data["locations"]:
                return jsonify(
                    {"error": "locations must contain at least one valid room object"}
                ), 400
            verrors = _validation_errors_for_game(game_data)
            if verrors:
                return jsonify(
                    {"error": "Game JSON failed validation", "details": verrors[:20]}
                ), 400
            game_json_str = json.dumps(game_data, ensure_ascii=False)
        else:
            game_json_str = row["game_json"]

        conn.execute(
            """
            UPDATE game_content
            SET title = ?, description = ?, genre = ?, game_json = ?, updated_at = datetime('now')
            WHERE id = ? AND user_id = ?
            """,
            (title, description, genre, game_json_str, story_id, g.user_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@app.route("/game-content/<int:story_id>", methods=["DELETE"])
@login_required
def delete_game_content(story_id: int):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM game_content WHERE id = ? AND user_id = ?",
            (story_id, g.user_id),
        ).fetchone()
        if not row:
            return jsonify({"error": "Story not found"}), 404

        adv_count = conn.execute(
            "SELECT COUNT(*) as c FROM adventures WHERE game_content_id = ?",
            (story_id,),
        ).fetchone()["c"]
        if adv_count > 0:
            return jsonify(
                {
                    "error": f"Cannot delete: {adv_count} adventure(s) use this story. Delete them first."
                }
            ), 409

        conn.execute(
            "DELETE FROM game_content WHERE id = ? AND user_id = ?",
            (story_id, g.user_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@app.route("/game-content/<int:story_id>/publish", methods=["POST"])
@login_required
def publish_game_content(story_id: int):
    new_state = 0
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM game_content WHERE id = ? AND user_id = ?",
            (story_id, g.user_id),
        ).fetchone()
        if not row:
            return jsonify({"error": "Story not found"}), 404

        new_state = 0 if row["is_public"] else 1
        conn.execute(
            "UPDATE game_content SET is_public = ?, updated_at = datetime('now') WHERE id = ?",
            (new_state, story_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "is_public": bool(new_state)})


@app.route("/community", methods=["GET"])
def browse_community():
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT gc.id, gc.title, gc.description, gc.genre, gc.play_count,
                   gc.created_at, gc.is_global, gc.game_json,
                   u.uid as author_name,
                   ou.uid as original_author_name
            FROM game_content gc
            LEFT JOIN users u ON gc.user_id = u.id
            LEFT JOIN users ou ON gc.original_author_id = ou.id
            WHERE gc.is_public = 1 OR gc.is_global = 1
            ORDER BY gc.is_global DESC, gc.play_count DESC, gc.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    stories = []
    for r in rows:
        try:
            parsed = json.loads(r["game_json"])
            graph_type = parsed.get("graph_type", "standard")
        except (json.JSONDecodeError, TypeError):
            graph_type = "standard"
        stories.append(
            {
                "id": r["id"],
                "title": r["title"],
                "description": r["description"],
                "genre": r["genre"],
                "play_count": r["play_count"],
                "author": r["author_name"] or "System",
                "original_author": r["original_author_name"]
                or r["author_name"]
                or "System",
                "is_global": bool(r["is_global"]),
                "created_at": r["created_at"],
                "graph_type": graph_type,
            }
        )
    return jsonify({"stories": stories})


def _llm_result_to_text(result) -> str:
    if isinstance(result, str):
        return result
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "".join(parts)
    return str(content)


def _strip_markdown_json_fences(text: str) -> str:
    s = text.strip()
    if not s.startswith("```"):
        return s
    s = s[3:]
    if s.lower().startswith("json"):
        s = s[4:].lstrip()
    if s.startswith("\n"):
        s = s[1:]
    else:
        idx = s.find("\n")
        if idx >= 0:
            s = s[idx + 1 :]
    fence = s.rfind("```")
    if fence >= 0:
        s = s[:fence]
    return s.strip()


@app.route("/generate-story", methods=["POST"])
@login_required
def generate_story():
    data = request.get_json(silent=True) or {}
    concept = (data.get("concept") or "").strip()
    if not concept:
        return jsonify({"error": "concept is required"}), 400
    if len(concept) > 5000:
        return jsonify({"error": "concept must be at most 5000 characters"}), 400

    graph_type = (data.get("graph_type") or "standard").strip().lower()

    if graph_type == "social":
        prompt = f"""You are a game designer for a parser-style text RPG (second-person, "you").

This story uses the "social" graph: dialogue-focused play with ordered milestones and a guide NPC who follows the player.

The user described this story idea:
---
{concept}
---

Output a single JSON object (no markdown, no code fences, no commentary) with this exact structure and field types:

- graph_type: string, must be exactly "social"
- title: string
- opening: string (second person, present tense; first thing the player reads)
- description: string (short catalog pitch, 1-2 sentences)
- genre: one of mystery, thriller, drama, comedy, sci-fi, horror, fantasy
- narrator_prompt: string (voice/style for the narrator; end beats with "What do you do?" where appropriate)
- player_name: string
- player_background: string
- player_traits: array of short strings (e.g. ["cautious", "witty"])
- guide: string (snake_case id of the NPC who follows the player between locations; must exactly match one characters[].key)
- milestones: array of 3 to 4 strings, ordered milestone goals the player should achieve in sequence
- locations: array of 1 to 3 objects, each with:
  - key: string (snake_case, e.g. "cafe_patio")
  - description: string (room/area description)
  - items: array of strings (can be empty)
- characters: array of 1 to 3 objects, each with:
  - key: string (snake_case NPC id)
  - personality: string (instructions for the NPC voice)
  - first_line: string (first spoken line)
  - location: string (must exactly match one locations[].key)
  - stall_threshold: integer (0 disables tension tracking; otherwise max turns without milestone progress before "stalling" mood)
  - tension_stages: array with the same length as milestones; index i describes behavior during milestone i. Each element is an object with:
    - progressing: string (how this NPC acts when the scene is moving forward)
    - stalling: string (how this NPC acts when interaction has stalled)
  Do NOT include a "mood" field on characters; use stall_threshold and tension_stages instead.

Ensure every character's location matches a location key, guide matches one character key, and each character's tension_stages has the same length as milestones.
Use consistent snake_case keys.
Respond with ONLY valid JSON."""
    else:
        prompt = f"""You are a game designer for a parser-style text RPG (second-person, "you").

The user described this story idea:
---
{concept}
---

Output a single JSON object (no markdown, no code fences, no commentary) with this exact structure and field types:

- title: string
- opening: string (second person, present tense; first thing the player reads)
- description: string (short catalog pitch, 1-2 sentences)
- genre: one of mystery, thriller, drama, comedy, sci-fi, horror, fantasy
- narrator_prompt: string (voice/style for the narrator; end beats with "What do you do?" where appropriate)
- player_name: string
- player_background: string
- player_traits: array of short strings (e.g. ["cautious", "witty"])
- locations: array of 1 to 3 objects, each with:
  - key: string (snake_case, e.g. "hotel_lobby")
  - description: string (room/area description)
  - items: array of strings (can be empty)
- characters: array of 1 to 3 objects, each with:
  - key: string (snake_case NPC id)
  - personality: string (instructions for the NPC voice)
  - first_line: string (first spoken line)
  - mood: integer 1-10
  - location: string (must exactly match one locations[].key)

Ensure every character's location matches a location key. Use consistent snake_case keys.
Respond with ONLY valid JSON."""

    text = ""
    try:
        llm = get_llm(DEFAULT_MODEL)
        raw = llm.invoke(prompt)
        text = _llm_result_to_text(raw)
        cleaned = _strip_markdown_json_fences(text)
        story = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(
            "generate-story invalid JSON: %s | snippet=%s",
            e,
            (text or "")[:200],
        )
        return jsonify(
            {
                "error": "The model did not return valid JSON. Try again or shorten your idea.",
                "detail": str(e),
            }
        ), 422
    except Exception as e:
        logger.exception("generate-story failed")
        return jsonify({"error": _llm_public_error_message(e)}), 500

    if not isinstance(story, dict):
        return jsonify({"error": "AI response was not a JSON object"}), 422

    return jsonify({"story": story, "prompt_used": prompt})


_IMPROVE_STORY_TEXT_FIELDS: dict[str, str] = {
    "opening": (
        "Opening prose the player reads first (before the starting room). "
        "Second person, present tense; set mood and hook without huge exposition dumps."
    ),
    "description": (
        "One- or two-sentence catalog pitch for the story browser: enticing, spoiler-light."
    ),
    "narrator_style": (
        "System instructions for the narrator LLM: tone, pacing, second person, never speak as NPCs, "
        "end beats with a clear player prompt (e.g. “What do you do?”) where appropriate."
    ),
    "player_background": (
        "Player character history and situation—concrete, playable, easy for the model to reuse in play."
    ),
    "location_description": (
        "What the player sees in this starting location: sensory detail, layout hints, mood. Second person."
    ),
    "character_prompt": (
        "System instructions for an NPC: personality, speech patterns, relationship to the player; "
        "the NPC speaks in first person as themselves."
    ),
    "character_first_line": (
        "The NPC’s first spoken line when the game begins—short, in-character."
    ),
}


@app.route("/improve-story-text", methods=["POST"])
@login_required
def improve_story_text():
    data = request.get_json(silent=True) or {}
    field = (data.get("field") or "").strip()
    text = (data.get("text") or "").strip()
    instruction = (data.get("instruction") or "").strip()

    if field not in _IMPROVE_STORY_TEXT_FIELDS:
        return jsonify({"error": "invalid field"}), 400
    if not text:
        return jsonify({"error": "text is required"}), 400
    if len(text) > 8000:
        return jsonify({"error": "text must be at most 8000 characters"}), 400
    if len(instruction) > 1500:
        return jsonify({"error": "instruction must be at most 1500 characters"}), 400

    purpose = _IMPROVE_STORY_TEXT_FIELDS[field]
    if instruction:
        task_block = f"Author request:\n{instruction}"
    else:
        task_block = (
            "Task: Improve the draft—fix awkward phrasing, tighten prose, keep facts and names consistent. "
            "Do not invent unrelated new plot unless the author asked for it."
        )

    prompt = f"""You help authors write content for a text-based RPG engine.

Field id: {field}
Purpose: {purpose}

Current draft:
---
{text}
---

{task_block}

Output rules:
- Reply with ONLY the replacement text for this field.
- No title line, no markdown code fences, no wrapping the entire answer in quotation marks."""

    try:
        llm = get_llm(DEFAULT_MODEL)
        raw = llm.invoke(prompt)
        out = _llm_result_to_text(raw).strip()
        if out.startswith("```"):
            out = _strip_markdown_json_fences(out)
        if len(out) >= 2 and out[0] in "\"'" and out[-1] == out[0]:
            out = out[1:-1].strip()
        if len(out) > 12000:
            out = out[:12000]
        return jsonify({"text": out, "prompt_used": prompt})
    except Exception as e:
        logger.exception("improve-story-text failed")
        return jsonify({"error": _llm_public_error_message(e)}), 500


# --- Gameplay (adventure-scoped) ---
@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    adventure_id = data.get("adventure_id")
    message = data.get("message", "")
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id"}), 400

    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        err = ensure_adventure_in_memory(conn, row)
        if err:
            return jsonify(err[1]), err[0]
        session_id = row["session_id"]
        slot = row["active_slot"]

        adv_lock = _get_adventure_lock(session_id)
        if not adv_lock.acquire(timeout=CHAT_LOCK_TIMEOUT_S):
            return jsonify(
                {
                    "error": "Another turn is still in progress. Try again in a moment.",
                }
            ), 429
        try:
            state = active_games[session_id]
            patch_state_engine_fields(state)
            if state.get("paused"):
                moods = {
                    name: char["mood"] for name, char in state["characters"].items()
                }
                return jsonify(
                    {
                        "response": "The game is paused. Unpause to continue playing.",
                        "moods": moods,
                        "location": state["location"],
                        "inventory": state.get("inventory", []),
                        "turns": state.get(
                            "turn_count", len(state.get("history") or [])
                        ),
                        "graph_type": state.get("_graph_type", "standard"),
                    }
                )

            sanitized_message = sanitize_input(message.strip())
            state["message"] = sanitized_message

            loc_key = state["location"]
            room_now = state["locations"].get(loc_key, {}) or {}
            state["narrative_turn_snapshot"] = {
                "location": loc_key,
                "inventory": list(state.get("inventory") or []),
                "room_item_names": list(room_now.get("items") or []),
            }

            graph_type = state.get("_graph_type", "standard")
            try:
                result = get_compiled_graph(graph_type).invoke(state)
            except Exception as e:
                logger.error(f"Chain execution error: {e}")
                return jsonify({"error": f"Internal error: {str(e)}"}), 500

            result.pop("narrative_turn_snapshot", None)
            result["_graph_type"] = graph_type
            active_games[session_id] = result
            upsert_save_slot_db(conn, aid, slot, result)
            conn.execute(
                "UPDATE adventures SET last_played = datetime('now') WHERE id = ?",
                (aid,),
            )
            conn.commit()

            moods = {name: char["mood"] for name, char in result["characters"].items()}
            milestones = result.get("milestones") or []
            m_progress = result.get("milestone_progress", 0)
            return jsonify(
                {
                    "response": result["response"],
                    "moods": moods,
                    "location": result["location"],
                    "inventory": result["inventory"],
                    "turns": result["turn_count"],
                    "milestones": milestones,
                    "milestone_progress": m_progress,
                    "current_milestone": milestones[m_progress] if m_progress < len(milestones) else None,
                    "tension_mood": result.get("tension_mood", "progressing"),
                    "tension_turns_since_milestone": result.get(
                        "tension_turns_since_milestone", 0
                    ),
                    "npc_tension": _npc_tension_map(result),
                    "memory_summary": result.get("memory_summary", ""),
                    "graph_type": result.get("_graph_type", "standard"),
                }
            )
        finally:
            adv_lock.release()
    finally:
        conn.close()


@app.route("/status", methods=["GET"])
@login_required
def status():
    adventure_id = request.args.get("adventure_id")
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id"}), 400

    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        err = ensure_adventure_in_memory(conn, row)
        if err:
            return jsonify(err[1]), err[0]
        session_id = row["session_id"]
        state = active_games[session_id]
        slots = get_save_slots_db(conn, aid)
    finally:
        conn.close()

    hist = state.get("history") or []
    milestones = state.get("milestones") or []
    m_progress = state.get("milestone_progress", 0)
    payload = {
        "location": state["location"],
        "graph_type": state.get("_graph_type", "standard"),
        "moods": {
            name: char["mood"] for name, char in state["characters"].items()
        },
        "turns": state["turn_count"],
        "inventory": state.get("inventory", []),
        "inventory_weight": f"{len(state.get('inventory', []))}/{INVENTORY_WEIGHT_LIMIT}",
        "paused": state.get("paused", False),
        "milestones": milestones,
        "milestone_progress": m_progress,
        "current_milestone": milestones[m_progress] if m_progress < len(milestones) else None,
        "tension_mood": state.get("tension_mood", "progressing"),
        "tension_turns_since_milestone": state.get("tension_turns_since_milestone", 0),
        "npc_tension": _npc_tension_map(state),
        "memory_summary": state.get("memory_summary", ""),
        "models": {
            "narrator": state["narrator"].get("model", DEFAULT_MODEL),
            "characters": {
                name: char.get("model", DEFAULT_MODEL)
                for name, char in state["characters"].items()
            },
        },
        "save_slots": slots,
        "history": hist,
        "adventure": {
            "id": row["id"],
            "name": row["name"],
            "game_file": row["game_file"],
            "active_slot": row["active_slot"],
        },
    }
    if not hist:
        payload["empty_history_opening"] = build_opening_message(state)
    return jsonify(payload)


@app.route("/save", methods=["POST"])
@login_required
def save():
    data = request.get_json(silent=True) or {}
    adventure_id = data.get("adventure_id")
    slot = data.get("slot", 0)
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
        slot = int(slot)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id or slot"}), 400

    if slot < 0 or slot >= SAVE_SLOTS:
        return jsonify({"error": "invalid slot"}), 400

    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        err = ensure_adventure_in_memory(conn, row)
        if err:
            return jsonify(err[1]), err[0]
        session_id = row["session_id"]
        upsert_save_slot_db(conn, aid, slot, active_games[session_id])
        conn.execute(
            "UPDATE adventures SET active_slot = ?, last_played = datetime('now') WHERE id = ?",
            (slot, aid),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@app.route("/resume", methods=["POST"])
@login_required
def resume():
    data = request.get_json(silent=True) or {}
    adventure_id = data.get("adventure_id")
    slot = data.get("slot", 0)
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
        slot = int(slot)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id or slot"}), 400

    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        session_id = row["session_id"]
        if not session_id:
            return jsonify({"error": "Adventure has no session"}), 400

        saved = load_save_slot_db(conn, aid, slot)
        if not saved:
            return jsonify({"error": "Save slot empty"}), 404

        patch_state_engine_fields(saved)
        active_games[session_id] = saved
        conn.execute(
            "UPDATE adventures SET active_slot = ?, last_played = datetime('now') WHERE id = ?",
            (slot, aid),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        {
            "ok": True,
            "turns": len(saved.get("history", [])),
            "location": saved["location"],
            "inventory": saved.get("inventory", []),
        }
    )


@app.route("/pause", methods=["POST"])
@login_required
def pause():
    data = request.get_json(silent=True) or {}
    adventure_id = data.get("adventure_id")
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id"}), 400

    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        err = ensure_adventure_in_memory(conn, row)
        if err:
            return jsonify(err[1]), err[0]
        active_games[row["session_id"]]["paused"] = True
    finally:
        conn.close()

    return jsonify({"ok": True, "paused": True})


@app.route("/unpause", methods=["POST"])
@login_required
def unpause():
    data = request.get_json(silent=True) or {}
    adventure_id = data.get("adventure_id")
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id"}), 400

    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        err = ensure_adventure_in_memory(conn, row)
        if err:
            return jsonify(err[1]), err[0]
        active_games[row["session_id"]]["paused"] = False
    finally:
        conn.close()

    return jsonify({"ok": True, "paused": False})


@app.route("/delete_save", methods=["DELETE"])
@login_required
def delete_save():
    data = request.get_json(silent=True) or {}
    adventure_id = data.get("adventure_id")
    slot = data.get("slot", 0)
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
        slot = int(slot)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id or slot"}), 400

    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        cur = conn.execute(
            "DELETE FROM save_slots WHERE adventure_id = ? AND slot = ?",
            (aid, slot),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Save slot empty"}), 404
    finally:
        conn.close()

    return jsonify({"ok": True})


@app.route("/list_slots", methods=["GET"])
@login_required
def list_slots():
    adventure_id = request.args.get("adventure_id")
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id"}), 400

    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        slots = get_save_slots_db(conn, aid)
    finally:
        conn.close()

    return jsonify({"slots": slots})


@app.route("/feedback", methods=["POST"])
@login_required
def feedback():
    """Append one playtest / design note to daily JSONL for later analysis."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    if len(text) > FEEDBACK_TEXT_MAX:
        return jsonify({"error": f"text exceeds {FEEDBACK_TEXT_MAX} characters"}), 400

    category = (data.get("category") or "general").lower().strip()
    if category not in FEEDBACK_CATEGORIES:
        category = "general"

    adventure_id = data.get("adventure_id")
    if adventure_id is None:
        return jsonify({"error": "adventure_id is required"}), 400
    try:
        aid = int(adventure_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid adventure_id"}), 400

    slot = data.get("slot", 0)
    conn = get_db()
    try:
        row = fetch_owned_adventure(conn, aid, g.user_id)
        if not row:
            return jsonify({"error": "Adventure not found"}), 404
        adv_game_file = row["game_file"]
        adv_name = row["name"]
        session_id = row["session_id"] or ""
    finally:
        conn.close()

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "adventure_id": aid,
        "session_id": session_id,
        "slot": slot,
        "game_file": data.get("game_file") or adv_game_file,
        "game_title": data.get("game_title") or adv_name,
        "category": category,
        "text": text,
    }

    if session_id and session_id in active_games:
        st = active_games[session_id]
        record["location"] = st.get("location")
        record["turn_count"] = st.get("turn_count")
        hist = st.get("history") or []
        if hist:
            record["history_tail"] = hist[-2:]

    snippet = (data.get("last_response_snippet") or "").strip()
    if snippet:
        record["last_response_snippet"] = snippet[:3000]

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = os.path.join(FEEDBACK_DIR, f"feedback_{day}.jsonl")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error(f"Feedback write failed: {e}")
        return jsonify({"error": "Could not write feedback file"}), 500

    logger.info(
        "Feedback recorded | game=%s | category=%s | %s",
        record.get("game_file"),
        category,
        text[:80],
    )
    return jsonify({"ok": True, "path": path})


init_db()
seed_global_games(str(GAMES_DIR))


if __name__ == "__main__":
    from config import ensure_dirs

    ensure_dirs()
    print(f"LangGraph RPG running on http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
