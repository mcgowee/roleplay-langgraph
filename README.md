# LangGraph RPG

A text-based adventure engine powered by LangGraph and Ollama LLMs.

## Features

- **Dynamic Narrative**: Local LLMs power narrator and NPC dialogue
- **State Management**: Full state graph pipeline (movement, inventory, narrator, mood, NPC, memory, rules)
- **NPC Moods**: Dynamic mood tracking (1-10) that affects dialogue
- **Save Slots**: Multiple save slots (0-4) with timestamps
- **Inventory Limits**: Configurable weight limits
- **Prompt Injection Protection**: Sanitized user input
- **Error Handling**: Graceful fallbacks on LLM errors
- **Logging**: Full audit trail with configurable log levels
- **Caching**: LLM instances cached for performance
- **Parallel Processing**: Concurrent NPC mood and response updates

For a **single index** of scripts, web UI, validation, story→JSON, feedback notes, and API surfaces, see **[documents/FEATURES.md](documents/FEATURES.md)**.

## Prerequisites

- Python 3.10+
- Ollama running locally at `http://localhost:11434`
- Required Ollama models (at minimum `llama3.1:8b`)
- Python virtual environment

## Installation

```bash
git clone <this-repo>
cd roleplay-langgraph
source ~/open-webui-env/bin/activate  # or your venv
pip install -r requirements.txt
# or: pip install flask requests langchain langchain_community langgraph
```

## Configuration

Copy `.env.example` to `.env` and adjust values:

```env
GAMES_DIR=/home/user/projects/roleplay-langgraph/games
SESSIONS_DIR=/home/user/projects/roleplay-langgraph/sessions
LOGS_DIR=/home/user/projects/roleplay-langgraph/logs
OLLAMA_HOST=http://localhost:11434
DEFAULT_MODEL=llama3.1:8b
FLASK_HOST=0.0.0.0
FLASK_PORT=5051
FLASK_DEBUG=false
HISTORY_LIMIT=6
SAVE_SLOTS=5
INVENTORY_WEIGHT_LIMIT=10
LOG_LEVEL=INFO
```

## Starting the Server

```bash
source ~/open-webui-env/bin/activate
cd ~/projects/roleplay-langgraph
python app.py
```

You should see:
```
LangGraph RPG running on http://0.0.0.0:5051
```

## Playing the Game

Open a second terminal:

```bash
source ~/open-webui-env/bin/activate
cd ~/projects/roleplay-langgraph
python play.py
```

## Web UI (SvelteKit, optional)

A small SvelteKit app proxies to Flask on the **server** (no CORS setup on Flask). **Lobby** and **Community** are readable without an account; **log in** to play, save, and manage **My Stories**. **Play:** chat UI with saves, pause, feedback. **Tools** (`/tools`): validate JSON, feedback report, story→draft (Ollama). Set **`RPG_REPO_ROOT`** in `web/.env` if you only run `npm run dev` from `web/`.

```bash
# Terminal 1 — API
python3 app.py

# Terminal 2 — UI
cd web
cp .env.example .env   # optional; defaults to http://127.0.0.1:5051
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`). Set `FLASK_API_URL` in `web/.env` if Flask is not on `127.0.0.1:5051`.

### Production build (bare metal)

```bash
cd web && npm ci && npm run build
HOST=0.0.0.0 PORT=3000 FLASK_API_URL=http://127.0.0.1:5051 npm start
```

### Docker (ship API + web)

See **[documents/SHIPPING.md](documents/SHIPPING.md)** for env vars, HTTPS, and smoke tests.

```bash
cp .env.example .env   # set SECRET_KEY and LLM settings
docker compose up --build
```

- UI: http://localhost:3000  
- API health: http://localhost:5051/games  

## In-Game Commands

| Command | What it does |
|---------|-------------|
| `status` | Shows location, turn count, NPC moods, inventory weight |
| `save {n}` | Save to slot n (0-4) |
| `load {n}` | Load from slot n |
| `list` | Show all save slots |
| `del {n}` | Delete slot n |
| `pause` | Pause the game |
| `unpause` | Resume the game |
| `quit` | Exit |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/games` | GET | List all available games |
| `/start` | POST | Start/resume a game (`{"game": "warehouse"}`) |
| `/chat` | POST | Send player action (`{"session_id": "...", "message": "..."}`) |
| `/status` | GET | Get current state (`?session_id=...`) |
| `/save` | POST | Save to slot (`{"session_id": "...", "slot": 0}`) |
| `/resume` | POST | Load from slot (`{"session_id": "...", "slot": 0}`) |
| `/pause` | POST | Pause game (`{"session_id": "..."}`) |
| `/unpause` | POST | Resume game |
| `/list_slots` | GET | List all save slots |
| `/delete_save` | DELETE | Delete specific slot |

## Game Structure

```json
{
  "title": "Game Title",
  "opening": "Opening text",
  "narrator": {"model": "llama3.1:8b", "prompt": "..."},
  "player": {"name": "Player", "background": "...", "traits": []},
  "characters": {
    "npc_name": {
      "model": "llama3.1:8b",
      "prompt": "Personality",
      "mood": 5,
      "mood_descriptions": {"1": "...", "10": "..."},
      "location": "start_location",
      "first_line": "Hello"
    }
  },
  "locations": {
    "location_name": {
      "description": "Description",
      "items": ["item1", "item2"],
      "characters": ["npc_name"]
    }
  },
  "rules": {
    "win": "Win condition",
    "lose": "Lose condition",
    "trigger_words": {"phrase": "response"}
  }
}
```

## Available Ollama Models

- `llama3.1:8b` — Clean prose, good for narrators
- `dolphin-mistral:latest` — Uncensored, edgy NPCs
- `mistral:7b-instruct` — General purpose
- `nchapman/mn-12b-mag-mell-r1:latest` — Creative characters
- `mistral-small:24b` — Most capable, slowest
- `deepseek-r1:14b` — Strong reasoning

## Game Pipeline

```
movement — detect if player is moving
    ↓
inventory — detect if player is picking up item
    ↓
narrator — generate scene description
    ↓
mood — evaluate and update NPC moods (parallel)
    ↓
npc — generate NPC dialogue (parallel)
    ↓
memory — save to history (circular buffer, limit 6)
    ↓
rules — check trigger words and win/lose
    ↓
END
```

## Creating New Games

### Using Designer

```bash
python designer.py
```

### From a story (upload / prose → JSON)

The engine does not read raw stories at play time; an LLM converts prose into the JSON shape above. See **`documents/STORY_TO_GAME.md`**, then:

```bash
python3 scripts/story_to_game_draft.py your_story.txt -o games/your_game.json
python3 scripts/validate_game_json.py games/your_game.json
```

Or paste the story into any AI chat with the instructions in that doc. Use **`GAME_DESIGN_PROMPT.md`** for interview-style authoring instead.

### Manual Creation

1. Create a JSON file in `games/`
2. Use lowercase keys for characters/locations
3. Match character names in location `characters` arrays
4. Provide mood descriptions for levels 1-10
5. Validate: `python3 scripts/validate_game_json.py games/your_file.json`

### From AI

See `GAME_DESIGN_PROMPT.md` for a structured prompt template.

## Development

### LLM Caching

LLM instances are cached by model name to avoid reconnection overhead. The module exposes `cleanup_llm_cache()` if you want to clear the cache on a graceful shutdown hook.

### Input Sanitization

All player input passes through `sanitize_input()` which blocks prompt injection attempts.

### Circular History Buffer

History is maintained as a circular buffer with configurable limit (`HISTORY_LIMIT` env var).

### Error Handling

All LLM calls have try/except blocks with fallback responses. Logs capture full error details.

## Troubleshooting

- **"Session not found"** — Call `/start` first or verify save slot exists
- **Slow responses** — Use smaller models (`llama3.1:8b`, `mistral:7b-instruct`)
- **Connection errors** — Ensure Ollama is running: `ollama serve`
- **No games found** — Check `games/` folder has `.json` files
- **Inventory full** — Max items configurable via `INVENTORY_WEIGHT_LIMIT`

## License

MIT
