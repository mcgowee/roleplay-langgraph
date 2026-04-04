# LangGraph RPG — feature & tool catalog

One place to see **everything** this repo exposes: runtime, authoring, validation, feedback, clients, and docs.

---

## Core runtime

| Piece | What it is | How to run |
|--------|------------|------------|
| **`app.py`** | Flask API + LangGraph pipeline (movement → inventory → narrator → mood → NPC → memory → rules) and persistence | `python3 app.py` (Ollama must be reachable) |
| **`play.py`** | Terminal client over HTTP | `python3 play.py` |
| **`config.py`** / **`.env`** | `GAMES_DIR`, `SESSIONS_DIR`, `LOGS_DIR`, `FEEDBACK_DIR`, Ollama host, default model, Flask port, save slots, etc. | Copy **`.env.example`** → **`.env`** |

---

## Creating game JSON (`games/*.json`)

| Option | Description | Command / action |
|--------|-------------|------------------|
| **Hand edit** | Edit JSON to match the shape in **`README.md`** or **`games/warehouse.json`** | Any editor |
| **`designer.py`** | Interactive terminal wizard writes a valid game file | `python3 designer.py` |
| **`GAME_DESIGN_PROMPT.md`** | Copy the fenced prompt into an AI chat; answer sections; save final JSON under **`games/`** | Open file, paste into chat |
| **`story_to_game_draft.py`** | Prose file → draft JSON via **local Ollama** | `python3 scripts/story_to_game_draft.py path/to/story.txt -o games/foo.json` |
| **`examples/sample_story_for_draft.txt`** | Example story input for the script above | Use as template |
| **`validate_game_json.py`** | Validate JSON **without** running the game | `python3 scripts/validate_game_json.py games/foo.json` or `--all` / `--strict` |

**Suggested flow:** draft (wizard / AI / story script) → **`validate_game_json.py`** → play.

See **`documents/STORY_TO_GAME.md`** and **`documents/GAME_DESIGN_CHECKLIST.md`**.

---

## Playtest notes (feedback JSONL)

Notes are **not** the same as save games. They append lines to **`logs/feedback/feedback_YYYYMMDD.jsonl`**.

| Where | How |
|-------|-----|
| **Flask** | `POST /feedback` (JSON body: `session_id`, `slot`, `game_file`, `game_title`, `category`, `text`, optional `last_response_snippet`) |
| **`play.py`** | `note …` or `/note …` or `/feedback …`; optional category prefix: `confusing`, `bug`, `praise`, `idea`, `pacing`, `tone`, `other` (else `general`) |
| **Web UI** | Session toolbar → **Playtest note** |
| **`feedback_report.py`** | Summarize notes for design iteration | `python3 scripts/feedback_report.py` · `--game stem` · `--brief` |

---

## Saves & session state

| Mechanism | Notes |
|-----------|--------|
| **Auto-save** | After each successful **`POST /chat`**, state is written under **`sessions/`** |
| **`play.py`** | `save n`, `load n`, `list`, `del n`, `pause`, `unpause`, `status`, etc. |
| **Flask** | `/save`, `/resume`, `/list_slots`, `/delete_save`, `/pause`, `/unpause`, `/status` |
| **Web UI** | Lobby save slot (0–4); toolbar: status, save, list saves, load/delete slot, pause/unpause |

`session_id` is typically `{game_file_stem}_{slot}` (e.g. `warehouse_0`).

---

## HTTP API (machine clients)

Full table in **`README.md`**. Includes: `/games`, `/start`, `/chat`, `/status`, save/resume/slots/delete, pause/unpause, **`/feedback`**.

---

## Web UI (`web/`)

SvelteKit **server proxy** to Flask (`FLASK_API_URL` in **`web/.env`**); browser does not need Flask CORS for those routes.

| Area | Features |
|------|----------|
| **Lobby** | Refresh games, pick save slot, **New game** / **Continue** per title |
| **Play** | Transcript + send messages (same as a turn in **`play.py`**) |
| **Session toolbar** | Game status, save now, list saves, pause/unpause, playtest note, end session |
| **Load / delete** | Load a slot into session; delete a slot (confirm) |
| **Tools** (`/tools`) | **Validate JSON** (runs `validate_game_json.py`), **Feedback report** (`feedback_report.py`), **Story → draft** (`story_to_game_draft.py` via Ollama). Requires `python3` on the server PATH and optional **`RPG_REPO_ROOT`** in `web/.env` if dev server cwd is not the repo root. |

```bash
# Terminal 1
python3 app.py

# Terminal 2
cd web && npm install && npm run dev
```

---

## Other Python

| File | Role |
|------|------|
| **`logger.py`** | Daily logs under **`logs/`** |
| **`test_nsfw.py`** | Standalone test script (optional) |

---

## Documentation index

| File | Contents |
|------|----------|
| **`README.md`** | Install, env, run server + CLI + web, API, game JSON shape |
| **`HOW_TO_PLAY.md`** | Player-oriented instructions |
| **`GAME_DESIGN_PROMPT.md`** | AI prompt for JSON + validator + engine tips |
| **`documents/LANGGRAPH_PIPELINE.md`** | Node order and Mermaid diagrams |
| **`documents/STORY_TO_GAME.md`** | Story → JSON (chat vs Ollama script) |
| **`documents/GAME_DESIGN_CHECKLIST.md`** | Authoring checklist |
| **`documents/FEATURES.md`** | This catalog |

---

## Quick “I want to…”

| Goal | Start here |
|------|----------------|
| **Ship a new game** | `designer.py` or `GAME_DESIGN_PROMPT.md` or `story_to_game_draft.py` → `validate_game_json.py` |
| **Capture playtest notes** | `note` / `/note` in **`play.py`** or web **Playtest note** → `feedback_report.py --brief` |
| **Play** | **`play.py`** or **`web/`** (with **`app.py`** + Ollama) |
| **Understand the graph** | **`documents/LANGGRAPH_PIPELINE.md`** |
