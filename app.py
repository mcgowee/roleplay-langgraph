from flask import Flask, g, jsonify, request, session
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
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

Is the player trying to move to a different location? If yes, reply with ONLY the exact location name from the list above. If no, reply with ONLY the word STAY."""

    try:
        result = llm.invoke(prompt).strip()
        for loc in location_names:
            if loc.lower() == result.lower() or loc.lower() in result.lower():
                if loc != state["location"]:
                    return {"location": loc}
                break
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

Is the player trying to pick up or take an item? If yes, reply with ONLY the exact item name from the list above. If no, reply with ONLY the word NONE."""

    try:
        result = llm.invoke(prompt).strip()
        for item in available_items:
            if item.lower() == result.lower() or item.lower() in result.lower():
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
    except Exception as e:
        logger.error(f"Inventory node error: {e}")

    return {}


def narrator_node(state: State) -> State:
    location = state["locations"][state["location"]]
    player = state["player"]
    history_text = "\n".join(state["history"][-6:])
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

    narrator_prompt = (state["narrator"].get("prompt") or "").strip() or DEFAULT_NARRATOR_PROMPT
    prompt = f"""{narrator_prompt}

Game: {state["game_title"]}
Player: {player.get("name", "Adventurer")} — {player.get("background", "")}
Current location: {state["location"]} — {location.get("description", "")}
Items here: {", ".join(location.get("items") or []) or "none"}
Player inventory: {", ".join(state["inventory"]) or "empty"}
Characters here: {", ".join(location.get("characters") or []) or "none"}
{arrival_hint}
Recent history:
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

        prompt = f"""You are evaluating how a character's mood should change after a conversation exchange.

Character: {npc_name} (current mood: {current_mood}/10)
Player action: {state["message"]}
Recent history:
{"\\n".join(state["history"][-4:])}

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

    history_text = "\n".join(state["history"][-6:])
    full_response = state["response"]

    def get_npc_response(npc_name: str) -> Optional[str]:
        if npc_name not in state["characters"]:
            return None

        npc = state["characters"][npc_name]
        mood = npc.get("mood", 5)
        mood_descriptions = npc.get("mood_descriptions", {})
        mood_desc = mood_descriptions.get(str(mood), f"Mood level {mood}/10.")
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
        prompt = f"""{npc_prompt}

You are speaking to {player.get("name", "Adventurer")}. {player.get("background", "")}.
Current mood: {mood_desc}

Recent history:
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

    if "WIN" in result:
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


# --- Graph ---
graph = StateGraph(State)
graph.add_node("movement", movement_node)
graph.add_node("inventory", inventory_node)
graph.add_node("narrator", narrator_node)
graph.add_node("mood", mood_node)
graph.add_node("npc", npc_node)
graph.add_node("memory", memory_node)
graph.add_node("rules", rules_node)

graph.set_conditional_entry_point(
    route_graph_entry,
    {"movement": "movement", "inventory": "inventory"},
)
graph.add_conditional_edges(
    "movement",
    route_after_movement,
    {"inventory": "inventory", "narrator": "narrator"},
)
graph.add_edge("inventory", "narrator")
graph.add_conditional_edges(
    "narrator",
    route_after_narrator,
    {"mood": "mood", "memory": "memory"},
)
graph.add_edge("mood", "npc")
graph.add_edge("npc", "memory")
graph.add_conditional_edges(
    "memory",
    route_after_memory,
    {END: END, "rules": "rules"},
)
graph.add_edge("rules", END)

chain = graph.compile()


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

    stories = [
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
        }
        for r in rows
    ]
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
                   gc.created_at, gc.is_global,
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

    stories = [
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
        }
        for r in rows
    ]
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

    return jsonify({"story": story})


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
        return jsonify({"text": out})
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
            sanitized_message = sanitize_input(message.strip())
            state["message"] = sanitized_message

            try:
                result = chain.invoke(state)
            except Exception as e:
                logger.error(f"Chain execution error: {e}")
                return jsonify({"error": f"Internal error: {str(e)}"}), 500

            active_games[session_id] = result
            upsert_save_slot_db(conn, aid, slot, result)
            conn.execute(
                "UPDATE adventures SET last_played = datetime('now') WHERE id = ?",
                (aid,),
            )
            conn.commit()

            moods = {name: char["mood"] for name, char in result["characters"].items()}
            return jsonify(
                {
                    "response": result["response"],
                    "moods": moods,
                    "location": result["location"],
                    "inventory": result["inventory"],
                    "turns": result["turn_count"],
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
    payload = {
        "location": state["location"],
        "moods": {
            name: char["mood"] for name, char in state["characters"].items()
        },
        "turns": state["turn_count"],
        "inventory": state.get("inventory", []),
        "inventory_weight": f"{len(state.get('inventory', []))}/{INVENTORY_WEIGHT_LIMIT}",
        "paused": state.get("paused", False),
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
