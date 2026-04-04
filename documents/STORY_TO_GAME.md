# From a story to a game JSON

You can turn prose (short story, outline, script, novel excerpt) into a `**games/*.json**` file in two main ways: **any AI chat** (upload or paste), or a **local script** that calls Ollama.

## What “upload a story” really means

The engine does not ingest raw prose at runtime. Something must **map** the story onto the fixed JSON schema (locations, characters with `prompt` / `mood_descriptions`, `narrator.prompt`, `rules`, etc.). That mapping is a **generation** step—best done by an LLM plus your **validator**.

Always run after generation:

```bash
python3 scripts/validate_game_json.py games/your_file.json
```

## Option A — Chat (Claude, ChatGPT, Cursor, etc.)

1. Upload the story file or paste the text.
2. Paste the **system / instruction** block from `scripts/story_to_game_draft.py` (constant `STORY_TO_GAME_INSTRUCTIONS`) *or* the shorter prompt below.
3. Ask for **only** valid JSON, no markdown fences if possible.
4. Save as `games/name.json`, then validate.

**Short prompt you can paste after the story:**

> Convert the story above into a single JSON object for our text RPG engine. The schema must match `games/warehouse.json`: `title`, `opening`, `narrator` { `model`, `prompt` }, `player` { `name`, `background`, `traits` }, `characters` { lowercase_id: { `model`, `prompt`, `mood`, `mood_descriptions` "1"–"10", `location`, `first_line` } }, `locations` { key: { `description`, `items`, `characters` } }, `rules` { `win`, `lose`, `trigger_words` }. Use `rules.trigger_words` only (not top-level). First key in `locations` is the starting room. Output nothing but the JSON.

## Option B — Local draft via Ollama

1. **Ollama** running (`ollama serve` if needed) and the model **pulled** (e.g. `ollama pull llama3.1:8b`).
2. `**requests`**: `pip install requests` (or `pip install -r requirements.txt` from the repo root).
3. From the repo root:

```bash
python3 scripts/story_to_game_draft.py examples/sample_story_for_draft.txt -o games/sample_from_story.json
```

Use your own story file instead of the sample when ready. The script reads `**OLLAMA_HOST**` and `**DEFAULT_MODEL**` from `config` / `.env` unless you pass `**--host**` or `**-m**`.

1. Fix any validator errors, then play: `python3 play.py` and pick `**sample_from_story**` (or your filename without `.json`).

```bash
python3 scripts/story_to_game_draft.py path/to/your_story.txt -o games/my_game.json
python3 scripts/validate_game_json.py games/my_game.json
```

Optional: `-m llama3.1:8b`, `--dry-run` (print prompt only, no API call), `--no-validate` (skip validator after write).

Large stories hit context limits—**summarize or split** (e.g. one act per run, then merge JSON by hand) if the model truncates.

## Option C — Hybrid

1. Use the script or chat for a **first draft**.
2. Paste `**python3 scripts/feedback_report.py --brief`** (playtest notes) into the same chat and ask for a **revised** JSON.
3. Validate again.

## Limits to expect

- Models **hallucinate** field names (`tone` vs `prompt`, `win_condition` vs `win`)—the validator catches those.
- **Pacing and win/lose** need human tuning after a playtest.
- Very long source material should be **chunked** or **outlined** first.

