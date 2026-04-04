# LangGraph RPG — How to Start and Play

## Prerequisites

- Python 3.12
- Ollama running locally at `http://localhost:11434`
- Required Ollama models pulled (at minimum `llama3.1:8b`)
- Python virtual environment at `~/open-webui-env`

## Starting the Server

```bash
source ~/open-webui-env/bin/activate
cd ~/projects/roleplay-langgraph
python app.py
```

You should see:

```
LangGraph RPG running on port 5051
```

Leave this terminal running.

## Playing the Game

Open a second terminal:

```bash
source ~/open-webui-env/bin/activate
cd ~/projects/roleplay-langgraph
python play.py
```

You will see a list of available games. Pick one by number and press Enter.

### In-Game Commands

| Command  | What it does                                      |
|----------|---------------------------------------------------|
| `status` | Shows your current location, turn count, NPC moods, and inventory |
| `quit`   | Ends the game                                     |

Anything else you type is treated as a player action. Examples:

- `look around`
- `talk to Magnus`
- `pick up the crowbar`
- `go to the loading bay`
- `open the crate`

### Session Resume

Your game is saved automatically after every turn. When you start a game that has a saved session, you will be asked whether to resume or start fresh.

Saved sessions are stored in `sessions/` as JSON files.

## API Endpoints

The Flask server exposes these endpoints if you want to interact directly:

| Endpoint  | Method | Description                        | Body                                      |
|-----------|--------|------------------------------------|-------------------------------------------|
| `/games`  | GET    | List all available games           | —                                         |
| `/start`  | POST   | Start or resume a game             | `{"game": "warehouse", "fresh": false}`   |
| `/chat`   | POST   | Send a player action               | `{"session_id": "warehouse", "message": "look around"}` |
| `/status` | GET    | Get current game state             | Query param: `?session_id=warehouse`      |

## Creating New Games

Place a new JSON file in the `games/` folder. See `GAME_DESIGN_PROMPT.md` for the full structure and how to generate one.

You can also run the interactive designer:

```bash
python designer.py
```

## Game Pipeline

Each player action flows through this pipeline:

```
movement — detect if the player is moving to a new location
    ↓
inventory — detect if the player is picking up an item
    ↓
narrator — generate atmospheric scene description
    ↓
mood — evaluate and adjust NPC moods
    ↓
npc — generate responses from all NPCs in the current location
    ↓
memory — save the turn to history
    ↓
rules — check trigger words and win/lose conditions
```

## Troubleshooting

- **"Session not found"** — You need to call `/start` before `/chat`. In `play.py` this happens automatically.
- **Slow responses** — Larger Ollama models (24b, 14b) take longer. Use `llama3.1:8b` or `mistral:7b-instruct` for faster turns.
- **Ollama connection error** — Make sure Ollama is running: `ollama serve`
- **No games found** — Make sure there is at least one `.json` file in the `games/` folder.
