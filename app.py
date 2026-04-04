from flask import Flask, g, jsonify, request, session
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
import json
import os
import secrets
import sqlite3
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
from db import get_db, init_db
from llm import get_llm, cleanup_llm_cache
from logger import get_logger

logger = get_logger(__name__)

DEFAULT_NARRATOR_PROMPT = (
    "You are the narrator for a text adventure. Describe scenes in second person. "
    "Do not speak as an NPC. End each beat with: What do you do?"
)

app = Flask(__name__)
app.secret_key = SECRET_KEY

FEEDBACK_CATEGORIES = frozenset(
    {"general", "confusing", "bug", "praise", "idea", "pacing", "tone", "other"}
)
FEEDBACK_TEXT_MAX = 8000

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
    n.setdefault("model", DEFAULT_MODEL)
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
        c.setdefault("model", DEFAULT_MODEL)
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


def patch_state_engine_fields(state: dict) -> None:
    """Fill missing keys from hand-edited or AI-generated game JSON and old saves."""
    state["narrator"] = normalize_narrator(state.get("narrator"))
    state["characters"] = normalize_characters(state.get("characters"))
    state["player"] = normalize_player(state.get("player"))
    state["rules"] = normalize_rules(state.get("rules"))


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
        "locations": game["locations"],
        "rules": normalize_rules(game.get("rules")),
        "game_title": game["title"],
        "opening": game.get("opening", "") or "",
        "inventory": [],
        "turn_count": 0,
        "paused": False,
    }


# --- Nodes ---
def movement_node(state: State) -> State:
    """Detect if the player is trying to move to a new location."""
    location_names = list(state["locations"].keys())
    if len(location_names) <= 1:
        return {"turn_count": state["turn_count"] + 1}

    model = state["narrator"].get("model", DEFAULT_MODEL)
    try:
        llm = get_llm(model)
    except Exception as e:
        logger.error(f"Failed to get LLM: {e}")
        return {"turn_count": state["turn_count"] + 1}

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
                    return {"location": loc, "turn_count": state["turn_count"] + 1}
                break
    except Exception as e:
        logger.error(f"Movement node error: {e}")

    return {"turn_count": state["turn_count"] + 1}


def inventory_node(state: State) -> State:
    """Detect if the player is trying to pick up an item with weight check."""
    location = state["locations"][state["location"]]
    available_items = location.get("items", [])
    if not available_items:
        return {"turn_count": state["turn_count"] + 1}

    model = state["narrator"].get("model", DEFAULT_MODEL)
    try:
        llm = get_llm(model)
    except Exception as e:
        logger.error(f"Failed to get LLM: {e}")
        return {"turn_count": state["turn_count"] + 1}

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
                        "turn_count": state["turn_count"] + 1,
                    }
                updated_locations = json.loads(json.dumps(state["locations"]))
                updated_locations[state["location"]]["items"].remove(item)
                new_inventory = state["inventory"] + [item]
                return {
                    "locations": updated_locations,
                    "inventory": new_inventory,
                    "turn_count": state["turn_count"] + 1,
                }
    except Exception as e:
        logger.error(f"Inventory node error: {e}")

    return {"turn_count": state["turn_count"] + 1}


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
            "turn_count": state["turn_count"] + 1,
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
Current location: {state["location"]} — {location["description"]}
Items here: {", ".join(location["items"]) or "none"}
Player inventory: {", ".join(state["inventory"]) or "empty"}
Characters here: {", ".join(location["characters"]) or "none"}
{arrival_hint}
Recent history:
{history_text}

Player just said: {state["message"]}

Narrate what happens next:"""

    try:
        narration = llm.invoke(prompt)
        return {"response": narration, "turn_count": state["turn_count"] + 1}
    except Exception as e:
        logger.error(f"Narrator node error: {e}")
        return {
            "response": f"[Error: {str(e)}]\n\nLocation: {location['description']}",
            "turn_count": state["turn_count"] + 1,
        }


def mood_node(state: State) -> State:
    characters = state["characters"]
    updated_characters = dict(characters)

    if not characters:
        return {"turn_count": state["turn_count"] + 1}

    # Parallelize mood updates
    def update_mood(npc_name: str, npc: dict) -> tuple:
        current_mood = npc.get("mood", 5)
        model = npc.get("model", DEFAULT_MODEL)
        try:
            llm = get_llm(model)
        except Exception as e:
            logger.error(f"Failed to get LLM for {npc_name}: {e}")
            return npc_name, current_mood

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
            executor.submit(update_mood, name, char)
            for name, char in characters.items()
        ]
        for future in as_completed(futures):
            name, updated_char = future.result()
            updated_characters[name] = updated_char

    return {"characters": updated_characters, "turn_count": state["turn_count"] + 1}


def npc_node(state: State) -> State:
    location = state["locations"][state["location"]]
    npcs_here = location["characters"]

    if not npcs_here:
        return {"turn_count": state["turn_count"] + 1}

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

    return {"response": full_response, "turn_count": state["turn_count"] + 1}


def memory_node(state: State) -> State:
    turn = f"Player: {state['message']}\n{state['response']}"
    new_history = add_to_history(list(state["history"]), turn, HISTORY_LIMIT)
    return {"history": new_history, "turn_count": state["turn_count"] + 1}


def rules_node(state: State) -> State:
    """Check win/lose conditions and trigger words with validation."""
    rules = state["rules"]
    message_lower = state["message"].lower()
    response = state["response"]

    # Check trigger words first
    for trigger, result_text in rules.get("trigger_words", {}).items():
        if trigger.lower() in message_lower:
            response = f"{response}\n\n{result_text}"
            return {"response": response, "turn_count": state["turn_count"] + 1}

    # Check win/lose conditions
    win_cond = rules.get("win", "")
    lose_cond = rules.get("lose", "")
    if not win_cond and not lose_cond:
        return {"turn_count": state["turn_count"] + 1}

    try:
        model = state["narrator"].get("model", DEFAULT_MODEL)
        llm = get_llm(model)
    except Exception as e:
        logger.error(f"Failed to get LLM: {e}")
        return {"turn_count": state["turn_count"] + 1}

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
        return {"turn_count": state["turn_count"] + 1}

    if "WIN" in result:
        response = f"{response}\n\n🏆 [GAME OVER — YOU WIN! {win_cond}]"
    elif "LOSE" in result:
        response = f"{response}\n\n💀 [GAME OVER — YOU LOSE! {lose_cond}]"

    return {"response": response, "turn_count": state["turn_count"] + 1}


# --- Graph ---
graph = StateGraph(State)
graph.add_node("movement", movement_node)
graph.add_node("inventory", inventory_node)
graph.add_node("narrator", narrator_node)
graph.add_node("mood", mood_node)
graph.add_node("npc", npc_node)
graph.add_node("memory", memory_node)
graph.add_node("rules", rules_node)

graph.set_entry_point("movement")
graph.add_edge("movement", "inventory")
graph.add_edge("inventory", "narrator")
graph.add_edge("narrator", "mood")
graph.add_edge("mood", "npc")
graph.add_edge("npc", "memory")
graph.add_edge("memory", "rules")
graph.add_edge("rules", END)

chain = graph.compile()


# --- Game state in memory (keyed by per-adventure session_id string) ---
active_games = {}


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

    try:
        state = load_game(row["game_file"])
    except Exception as e:
        logger.error("Failed to reload game %s: %s", row["game_file"], e)
        return 404, {"error": f"Game not found: {row['game_file']}"}

    active_games[session_id] = state
    return None


def build_opening_message(state: dict) -> str:
    room_desc = state["locations"][state["location"]]["description"]
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
    games = []
    for filename in sorted(os.listdir(GAMES_DIR)):
        if filename.endswith(".json"):
            path = os.path.join(GAMES_DIR, filename)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                games.append(
                    {
                        "file": filename.replace(".json", ""),
                        "title": data.get("title", filename),
                        "opening": data.get("opening", ""),
                        "narrator_model": data.get("narrator", {}).get(
                            "model", DEFAULT_MODEL
                        ),
                        "character_models": {
                            name: char.get("model", DEFAULT_MODEL)
                            for name, char in data.get("characters", {}).items()
                        },
                    }
                )
            except Exception as e:
                logger.error(f"Error reading game {filename}: {e}")
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
            SELECT id, game_file, name, session_id, created_at, last_played
            FROM adventures
            WHERE user_id = ?
            ORDER BY last_played DESC NULLS LAST, created_at DESC
            """,
            (g.user_id,),
        ).fetchall()
    finally:
        conn.close()

    adventures = [
        {
            "id": r["id"],
            "game_file": r["game_file"],
            "name": r["name"],
            "session_id": r["session_id"],
            "created_at": r["created_at"],
            "last_played": r["last_played"],
        }
        for r in rows
    ]
    return jsonify({"adventures": adventures})


@app.route("/adventures", methods=["POST"])
@login_required
def create_adventure():
    data = request.get_json(silent=True) or {}
    game_file = (data.get("game_file") or "").strip().replace(".json", "")
    if not game_file:
        return jsonify({"error": "game_file is required"}), 400

    game_path = os.path.join(GAMES_DIR, f"{game_file}.json")
    if not os.path.isfile(game_path):
        return jsonify({"error": f"Game not found: {game_file}"}), 404

    try:
        with open(game_path, "r") as f:
            game_json = json.load(f)
    except OSError as e:
        logger.error("Read game %s: %s", game_path, e)
        return jsonify({"error": "Could not read game file"}), 500

    name = (data.get("name") or "").strip() or game_json.get("title") or game_file

    try:
        state = load_game(game_file)
    except Exception as e:
        logger.error("load_game %s: %s", game_file, e)
        return jsonify({"error": f"Invalid game: {game_file}"}), 400

    session_key = f"adv_{secrets.token_hex(16)}"
    active_games[session_key] = state
    opening = build_opening_message(state)

    conn = get_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO adventures (user_id, game_file, name, session_id, last_played)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (g.user_id, game_file, name, session_key),
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

        conn.execute("DELETE FROM save_slots WHERE adventure_id = ?", (adventure_id,))
        conn.execute(
            "DELETE FROM adventures WHERE id = ? AND user_id = ?",
            (adventure_id, g.user_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


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


if __name__ == "__main__":
    from config import ensure_dirs

    ensure_dirs()
    print(f"LangGraph RPG running on http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
