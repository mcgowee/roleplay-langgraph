import requests
import os
import sys
from getpass import getpass

from config import FLASK_HOST, FLASK_PORT, SAVE_SLOTS, HISTORY_LIMIT

API = f"http://{FLASK_HOST}:{FLASK_PORT}"

session = requests.Session()

# Optional first word after /note or /feedback (not "general")
_NOTE_CATEGORIES = frozenset(
    {"confusing", "bug", "praise", "idea", "pacing", "tone", "other"}
)


def clear():
    os.system("clear")


def print_divider():
    print("\n" + "─" * 60 + "\n")


def login_or_register():
    print("Log in or register to play.\n")
    while True:
        try:
            uid = input("  Username: ").strip()
            password = getpass("  Password: ")
            lr = input("  (L)ogin or (R)egister? ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            sys.exit(0)

        if lr in ("r", "register"):
            try:
                res = session.post(f"{API}/register", json={"uid": uid, "password": password})
            except requests.exceptions.ConnectionError:
                print("\nError: Could not connect to game server.")
                print(f"Make sure the server is running at {API}\n")
                continue
            if res.status_code == 201:
                try:
                    data = res.json()
                except ValueError:
                    print("\n\033[91mInvalid response from server.\033[0m\n")
                    continue
                print(f"\n\033[92mWelcome, {data.get('uid', uid)}!\033[0m\n")
                return
            if res.status_code == 409:
                try:
                    err = res.json().get("error", "Username already taken")
                except ValueError:
                    err = "Username already taken"
                print(f"\n\033[91m{err}\033[0m\n")
                continue
            try:
                err = res.json().get("error", res.text[:120])
            except ValueError:
                err = res.text[:120]
            print(f"\n\033[91m{err}\033[0m\n")
            continue

        if lr in ("l", "login", ""):
            try:
                res = session.post(f"{API}/login", json={"uid": uid, "password": password})
            except requests.exceptions.ConnectionError:
                print("\nError: Could not connect to game server.")
                print(f"Make sure the server is running at {API}\n")
                continue
            if res.status_code == 200:
                try:
                    data = res.json()
                except ValueError:
                    print("\n\033[91mInvalid response from server.\033[0m\n")
                    continue
                print(f"\n\033[92mWelcome back, {data.get('uid', uid)}!\033[0m\n")
                return
            if res.status_code == 401:
                try:
                    err = res.json().get("error", "Invalid uid or password")
                except ValueError:
                    err = "Invalid uid or password"
                print(f"\n\033[91m{err}\033[0m\n")
                continue
            try:
                err = res.json().get("error", res.text[:120])
            except ValueError:
                err = res.text[:120]
            print(f"\n\033[91m{err}\033[0m\n")
            continue

        print("Type L for login or R for register.")


def pick_game():
    try:
        res = session.get(f"{API}/games")
        games = res.json().get("games", [])
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to game server.")
        print(f"Make sure the server is running at {API}")
        sys.exit(1)
    except ValueError:
        print("Error: Invalid response from game server.")
        sys.exit(1)

    if not games:
        print("No games found in the games folder.")
        sys.exit(1)

    print("╔══════════════════════════════════════════════════════════╗")
    print("║              LANGGRAPH RPG                               ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print("\nAvailable games:\n")

    for i, game in enumerate(games, 1):
        print(f"  {i}. {game['title']}")
        if game["opening"]:
            print(f"     \033[90m{game['opening'][:70]}...\033[0m")
        print()

    while True:
        try:
            choice = input("Pick a game (number): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(games):
                g = games[idx]
                gid = g.get("id")
                if gid is not None:
                    return int(gid), g["title"]
                return g["file"], g["title"]
            print("Invalid choice. Try again.")
        except (ValueError, KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            sys.exit(0)


def _create_new_adventure(game_ref):
    """game_ref is either game_content_id (int) or legacy file stem (str)."""
    try:
        payload = (
            {"game_content_id": int(game_ref)}
            if isinstance(game_ref, int)
            else {"game_file": game_ref}
        )
        res = session.post(f"{API}/adventures", json=payload)
        data = res.json()
    except requests.exceptions.ConnectionError:
        print("\nError: Could not connect to game server.")
        sys.exit(1)
    except ValueError:
        print("\nError: Invalid response from game server.")
        sys.exit(1)

    if res.status_code != 200:
        print(f"\n\033[91m{data.get('error', 'Could not start adventure')}\033[0m")
        sys.exit(1)

    adventure = data.get("adventure") or {}
    aid = adventure.get("id")
    opening = data.get("response", "")
    slot = int(adventure.get("active_slot", 0))
    return aid, opening, slot


def start_game(game_ref, game_title_for_display: str):
    try:
        res = session.get(f"{API}/adventures")
        data = res.json()
    except requests.exceptions.ConnectionError:
        print("\nError: Could not connect to game server.")
        sys.exit(1)
    except ValueError:
        print("\nError: Invalid response from game server.")
        sys.exit(1)

    if res.status_code != 200:
        print(f"\n\033[91m{data.get('error', 'Could not list adventures')}\033[0m")
        sys.exit(1)

    if isinstance(game_ref, int):
        adventures = [
            a
            for a in data.get("adventures", [])
            if a.get("game_content_id") == game_ref
        ]
    else:
        adventures = [
            a for a in data.get("adventures", []) if a.get("game_file") == game_ref
        ]

    if not adventures:
        return _create_new_adventure(game_ref)

    print("\nYou have existing adventures for this game:\n")
    for i, a in enumerate(adventures, 1):
        lp = a.get("last_played") or ""
        if lp:
            lp = lp[:19].replace("T", " ")
        print(f"  {i}. {a['name']} (last played: {lp})")

    while True:
        try:
            choice = input(
                "\nContinue adventure (number) or start (N)ew? "
            ).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            sys.exit(0)

        if choice in ("n", "new"):
            return _create_new_adventure(game_ref)

        try:
            idx = int(choice) - 1
        except ValueError:
            print("Invalid choice. Enter a number or N for new.")
            continue

        if not (0 <= idx < len(adventures)):
            print("Invalid choice. Try again.")
            continue

        adventure_id = adventures[idx]["id"]
        st = get_status(adventure_id)
        if st.get("error"):
            print(f"\n\033[91mError: {st['error']}\033[0m")
            continue

        hist = st.get("history") or []
        if not hist:
            opening = st.get("empty_history_opening", "")
        else:
            opening = "\n\n".join(hist[-HISTORY_LIMIT:])

        adv_meta = st.get("adventure") or {}
        slot = int(adv_meta.get("active_slot", 0))
        return adventure_id, opening, slot


def send_message(adventure_id, message):
    try:
        res = session.post(
            f"{API}/chat",
            json={"adventure_id": adventure_id, "message": message},
        )
        return res.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Could not connect to server"}
    except ValueError:
        return {"error": "Invalid response from server"}


def get_status(adventure_id):
    try:
        res = session.get(f"{API}/status", params={"adventure_id": adventure_id})
        return res.json()
    except requests.exceptions.ConnectionError:
        return {}
    except ValueError:
        return {"error": "Invalid response from server"}


def submit_feedback(adventure_id, slot, game_file, game_title, category, text, last_response=None):
    payload = {
        "adventure_id": adventure_id,
        "slot": slot,
        "game_file": game_file,
        "game_title": game_title,
        "category": category,
        "text": text,
    }
    if last_response:
        payload["last_response_snippet"] = last_response[:3000]
    try:
        res = session.post(f"{API}/feedback", json=payload)
        if res.status_code == 200:
            path = res.json().get("path", "logs/feedback/")
            print(f"\n\033[92mFeedback saved ({path})\033[0m")
        else:
            try:
                err = res.json().get("error", res.text[:120])
            except ValueError:
                err = res.text[:120]
            print(f"\n\033[91mFeedback failed: {err}\033[0m")
    except requests.exceptions.ConnectionError:
        print("\n\033[91mCould not connect to server\033[0m")


def display_response(response, moods):
    print_divider()
    parts = response.split("\n\n")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "[" in part and "mood:" in part:
            continue
        if ":" in part[:30] and (
            part.startswith("Magnus:")
            or part.startswith("Captain:")
            or part.startswith("Maren:")
            or part.startswith("Homeless")
            or part.startswith("Earl:")
            or part[0].isupper()
        ):
            print(f"\033[93m{part}\033[0m")
        else:
            print(f"\033[3m{part}\033[0m")

    if moods:
        for name, mood in moods.items():
            bar = "█" * mood + "░" * (10 - mood)
            print(f"\n\033[90m{name.title()} mood: [{bar}] {mood}/10\033[0m")
    print_divider()


def display_help():
    """Display all available commands."""
    print("\n" + "─" * 40)
    print("  Available Commands")
    print("─" * 40)
    print("  /status      - Check game state")
    print("  /save {n}    - Save to slot n (0-4)")
    print("  /load {n}    - Load from slot n (0-4)")
    print("  /list        - Show save slots")
    print("  /del {n}     - Delete slot n")
    print("  /pause       - Pause the game")
    print("  /unpause     - Resume the game")
    print("  /note [cat]  - Save playtest note (see /help)")
    print("  /quit        - Exit the game")
    print("  /help        - Show this help menu")
    print("  /note [category] text")
    print("    Save a line to logs/feedback/ for story or engine review.")
    print("    Categories: confusing, bug, praise, idea, pacing, tone, other")
    print("    Example: /note praise Magnus's dialogue landed perfectly")
    print("    Example: /note bug narrator repeated the same room description")
    print("─" * 40 + "\n")


def display_status(status):
    if "error" in status:
        print(f"\n\033[91mError: {status['error']}\033[0m")
        return
    inventory_weight = status.get("inventory_weight", "")
    print(
        f"\n\033[90m📍 Location: {status.get('location')} | "
        f"Turns: {status.get('turns')} | "
        f"Moods: {status.get('moods')} | "
        f"Inventory: {status.get('inventory', [])} "
        f"({inventory_weight})\033[0m"
    )


def save_game(adventure_id, slot):
    try:
        res = session.post(
            f"{API}/save", json={"adventure_id": adventure_id, "slot": slot}
        )
        if res.status_code == 200:
            print(f"\n\033[92mGame saved to slot {slot}\033[0m")
        else:
            try:
                err = res.json().get("error", "Unknown error")
            except ValueError:
                err = "Unknown error"
            print(f"\n\033[91mFailed to save: {err}\033[0m")
    except requests.exceptions.ConnectionError:
        print("\n\033[91mCould not connect to server\033[0m")


def list_slots(adventure_id):
    res = None
    try:
        res = session.get(f"{API}/list_slots", params={"adventure_id": adventure_id})
        if res.status_code != 200:
            print(f"\n\033[91mAPI Error: {res.status_code} - {res.text[:100]}\033[0m")
            return
        slots = res.json().get("slots", [])
        if not slots:
            print("\n\033[90mNo save slots found.\033[0m")
            return
        print("\n\033[90mSave Slots:\033[0m")
        for slot in slots:
            timestamp = slot.get("timestamp", "unknown")[:19].replace("T", " ")
            print(
                f"  Slot {slot['slot']}: {timestamp} | Turn {slot['turns']} | {slot['location']}"
            )
    except requests.exceptions.ConnectionError:
        print("\n\033[91mCould not connect to server\033[0m")
    except ValueError:
        if res is not None:
            print(f"\n\033[91mInvalid response from server: {res.text[:200]}\033[0m")
        else:
            print("\n\033[91mInvalid response from server\033[0m")


def delete_slot(adventure_id, slot):
    try:
        res = session.delete(
            f"{API}/delete_save", json={"adventure_id": adventure_id, "slot": slot}
        )
        if res.status_code == 200:
            print(f"\n\033[92mDeleted slot {slot}\033[0m")
        else:
            try:
                err = res.json().get("error", "Unknown error")
            except ValueError:
                err = "Unknown error"
            print(f"\n\033[91mFailed to delete: {err}\033[0m")
    except requests.exceptions.ConnectionError:
        print("\n\033[91mCould not connect to server\033[0m")


def main():
    clear()
    login_or_register()
    game_ref, game_title = pick_game()

    print(f"\n  \033[93m{game_title.upper()}\033[0m\n")
    print("  Type your actions and press Enter.")
    print("  Commands:")
    print("    status       - Check game state")
    print("    save {n}     - Save to slot n (0-4)")
    print("    load {n}     - Load from slot n (0-4)")
    print("    list         - Show save slots")
    print("    del {n}      - Delete slot n")
    print("    pause        - Pause the game")
    print("    unpause      - Resume the game")
    print("    note …       - Same as /note (playtest feedback file)")
    print("    quit         - Exit the game")
    print()

    adventure_id, opening, slot = start_game(game_ref, game_title)
    last_story_text = opening
    display_response(opening, {})

    while True:
        try:
            action = input("\033[96mYou:\033[0m ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGame ended.")
            break

        if not action:
            continue

        # Handle commands
        raw_input = action.strip()
        if raw_input.split(None, 1)[0].lower() in ("note", "feedback"):
            action = "/" + raw_input
        cmd_parts = action.lower().split()

        # Slash commands
        if cmd_parts[0].startswith("/"):
            slash_cmd = cmd_parts[0][1:]  # Remove leading "/"
            if slash_cmd == "quit":
                print("\nGame ended.")
                break
            elif slash_cmd == "status":
                status = get_status(adventure_id)
                display_status(status)
                continue
            elif slash_cmd == "help":
                display_help()
                continue
            elif slash_cmd == "save" and len(cmd_parts) == 2:
                try:
                    save_slot = int(cmd_parts[1])
                    if 0 <= save_slot < SAVE_SLOTS:
                        save_game(adventure_id, save_slot)
                    else:
                        print(
                            f"\n\033[91mInvalid slot. Must be 0-{SAVE_SLOTS - 1}\033[0m"
                        )
                except ValueError:
                    print("\n\033[91mUsage: /save {slot_number}\033[0m")
                continue
            elif slash_cmd == "load" and len(cmd_parts) == 2:
                try:
                    load_slot = int(cmd_parts[1])
                    if 0 <= load_slot < SAVE_SLOTS:
                        res = session.post(
                            f"{API}/resume",
                            json={"adventure_id": adventure_id, "slot": load_slot},
                        )
                        if res.status_code == 200:
                            slot = load_slot
                            try:
                                data = res.json()
                            except ValueError:
                                print("\n\033[91mInvalid response from server\033[0m")
                                continue
                            print(
                                f"\n\033[92mLoaded slot {load_slot} - Turn {data['turns']}\033[0m"
                            )
                        else:
                            try:
                                err = res.json().get("error", "Failed to load")
                            except ValueError:
                                err = "Failed to load"
                            print(f"\n\033[91m{err}\033[0m")
                    else:
                        print(
                            f"\n\033[91mInvalid slot. Must be 0-{SAVE_SLOTS - 1}\033[0m"
                        )
                except ValueError:
                    print("\n\033[91mUsage: /load {slot_number}\033[0m")
                continue
            elif slash_cmd == "list":
                list_slots(adventure_id)
                continue
            elif slash_cmd == "del" and len(cmd_parts) == 2:
                try:
                    del_slot = int(cmd_parts[1])
                    if 0 <= del_slot < SAVE_SLOTS:
                        delete_slot(adventure_id, del_slot)
                    else:
                        print(
                            f"\n\033[91mInvalid slot. Must be 0-{SAVE_SLOTS - 1}\033[0m"
                        )
                except ValueError:
                    print("\n\033[91mUsage: /del {slot_number}\033[0m")
                continue
            elif slash_cmd == "pause":
                try:
                    res = session.post(
                        f"{API}/pause", json={"adventure_id": adventure_id}
                    )
                    if res.status_code == 200:
                        print(f"\n\033[93mGame paused\033[0m")
                    else:
                        try:
                            err = res.json().get("error", "Failed to pause")
                        except ValueError:
                            err = "Failed to pause"
                        print(f"\n\033[91m{err}\033[0m")
                except requests.exceptions.ConnectionError:
                    print("\n\033[91mCould not connect to server\033[0m")
                continue
            elif slash_cmd == "unpause":
                try:
                    res = session.post(
                        f"{API}/unpause", json={"adventure_id": adventure_id}
                    )
                    if res.status_code == 200:
                        print(f"\n\033[92mGame resumed\033[0m")
                    else:
                        try:
                            err = res.json().get("error", "Failed to resume")
                        except ValueError:
                            err = "Failed to resume"
                        print(f"\n\033[91m{err}\033[0m")
                except requests.exceptions.ConnectionError:
                    print("\n\033[91mCould not connect to server\033[0m")
                continue
            elif slash_cmd in ("note", "feedback"):
                parts = action.strip().split(None, 1)
                if len(parts) < 2 or not parts[1].strip():
                    print(
                        "\n\033[93mUsage: /note [category] your message\033[0m"
                        "\n  Categories (optional): confusing, bug, praise, idea, pacing, tone, other"
                    )
                    continue
                rest = parts[1].strip()
                rest_tokens = rest.split(None, 1)
                first_w = rest_tokens[0].lower()
                if len(rest_tokens) == 2 and first_w in _NOTE_CATEGORIES:
                    category = first_w
                    note_text = rest_tokens[1].strip()
                else:
                    category = "general"
                    note_text = rest
                if not note_text:
                    print("\n\033[91mNote text is empty.\033[0m")
                    continue
                gfile = game_ref if isinstance(game_ref, str) else ""
                submit_feedback(
                    adventure_id,
                    slot,
                    gfile,
                    game_title,
                    category,
                    note_text,
                    last_response=last_story_text,
                )
                continue
            else:
                print(
                    f"\n\033[91mUnknown command: {slash_cmd}. Type /help for commands.\033[0m"
                )
                continue

        # Send regular message
        data = send_message(adventure_id, action)
        if "error" in data:
            print(f"\n\033[91mError: {data['error']}\033[0m")
            continue

        location = data.get("location", "")
        if location:
            print(f"\n\033[90m📍 {location}\033[0m")
        last_story_text = data.get("response", "") or last_story_text
        display_response(data.get("response", ""), data.get("moods", {}))


if __name__ == "__main__":
    main()
