# Game design checklist

Use this when authoring or reviewing a `games/*.json` file for this engine. See also `GAME_DESIGN_PROMPT.md` and `documents/LANGGRAPH_PIPELINE.md`.

**Automated check (no server):** `python3 scripts/validate_game_json.py games/your_game.json` or `--all` — see script help for `--strict`.

## Structure

- [ ] **Keys**: Character ids are lowercase and match `locations[].characters[]` exactly.
- [ ] **Starting location**: The first key in `locations` is where the player begins (JSON object order).
- [ ] **Character `location`**: Matches a `locations` key (used for designer consistency; presence in room is driven by each location’s `characters` list).

## Opening and first beat

- [ ] **`opening`**: Sets mood before room description; shown on **fresh** start (before the starting room text).
- [ ] **Room description**: Concrete exits, sensory detail, and anything the movement/inventory LLMs should align with.
- [ ] **`first_line`**: Only characters listed in the **starting** location should have lines you expect at game start.

## Narrator

- [ ] **Second person** (“you”) for scene description.
- [ ] **No NPC voice**: Narrator describes; dialogue comes from character nodes only.
- [ ] **Length**: Short beats (e.g. under ~6 sentences) keep turns snappy unless you want slow burn.
- [ ] **End cue**: e.g. “What do you do?” so the player knows the turn is theirs.

## Player

- [ ] **`background`** and **`traits`**: Used in narrator and NPC prompts — enough for consistent motivation and voice.

## NPCs

- [ ] **`prompt`**: Personality, speech patterns, relationship to the player, and what they want in the scene.
- [ ] **`mood_descriptions`**: All 10 levels describe **behavior** (what they say, allow, or refuse), not just adjectives.
- [ ] **Models**: Narrator vs NPC models match the tone and capability you need.

## Locations and items

- [ ] **Location names**: Clear and distinct — movement detection maps player text to these strings.
- [ ] **`items`**: Named simply — pickup detection matches against this list.
- [ ] **Empty rooms**: Fine for pacing; mood/NPC nodes skip when nobody is present.

## Rules

- [ ] **`trigger_words`**: Short phrases players are likely to type (substring match). Use for locks, props, and “you need X first” moments.
- [ ] **`win` / `lose`**: Phrase as **observable outcomes** (“Magnus explicitly agrees to let you leave with the ledger”) so the rules judge can recognize them from recent history.
- [ ] **Empty win/lose**: Omit or use `""` for open-ended/exploratory games.

## Playtest

- [ ] Try movement phrasing: “go to …”, “walk to …”, room name only.
- [ ] Try pickups: “take …”, “pick up …”.
- [ ] Confirm triggers fire on likely synonyms or add more trigger entries.
- [ ] Confirm an ending (if any) actually appears when you narrate success or failure clearly.
