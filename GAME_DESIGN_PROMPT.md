# Game Design Prompt

Copy and paste the prompt below into any AI chat to have it help you design a new game. It will ask you the right questions and output a valid JSON file you can drop into the `games/` folder.

---

## Prompt

```
I need you to help me create a game definition file for my text-based RPG engine. The engine runs on LangGraph and uses local Ollama LLM models to power a narrator and NPC characters. You will ask me questions one section at a time, then generate the final JSON file.

Here is the exact JSON structure you need to produce:

{
  "title": "",
  "opening": "",
  "narrator": {
    "model": "",
    "prompt": ""
  },
  "player": {
    "name": "",
    "background": "",
    "traits": []
  },
  "characters": {
    "character_name_lowercase": {
      "model": "",
      "prompt": "",
      "mood": 5,
      "mood_descriptions": {
        "1": "",
        "2": "",
        "3": "",
        "4": "",
        "5": "",
        "6": "",
        "7": "",
        "8": "",
        "9": "",
        "10": ""
      },
      "location": "",
      "first_line": ""
    }
  },
  "locations": {
    "location_name_lowercase": {
      "description": "",
      "items": [],
      "characters": []
    }
  },
  "rules": {
    "win": "",
    "lose": "",
    "trigger_words": {}
  }
}

AVAILABLE OLLAMA MODELS (the user must pick from these):
- llama3.1:8b — clean prose, supports tool calling, good for narrators
- dolphin-mistral:latest — uncensored, good for edgy or morally gray NPCs
- mistral:7b-instruct — balanced general purpose
- nchapman/mn-12b-mag-mell-r1:latest — creative, complex characters (slower)
- mistral-small:24b — most capable, slowest
- deepseek-r1:14b — strong reasoning

RULES FOR THE JSON:
- Character keys in the "characters" object must be lowercase (e.g. "magnus", not "Magnus")
- The "characters" array inside each location must use the same lowercase keys
- The "location" field on each character must exactly match a key in "locations"
- Every location should have a description, an items array (can be empty), and a characters array (can be empty)
- mood starts at 1-10 (5 is neutral). Provide a mood_descriptions entry for all 10 levels — these describe how the NPC behaves at that mood
- mood 1 = hostile/worst, mood 10 = fully trusting/best
- trigger_words are exact phrases the player might type that produce a hardcoded response (useful for examining objects, locked doors, etc.)
- win and lose are plain English descriptions of the conditions. The engine uses an LLM to judge when they are met. Leave empty string if no win/lose condition
- The narrator prompt should define the tone and style. It should instruct the narrator to describe in second person and never speak as a character
- Each character prompt should define personality, speech patterns, and relationship to the player
- first_line is what the character says when the game starts (only shown if they are in the starting location)
- The opening is shown in the game selection menu and, on a **new** game, appears once before the starting room description (sets mood; then the first location’s description and NPC first lines follow)

Ask me the following questions ONE SECTION AT A TIME. Wait for my answers before moving to the next section.

SECTION 1 — THE CONCEPT:
- What is the title of your game?
- What genre or tone? (noir, horror, comedy, fantasy, sci-fi, romance, etc.)
- Give me a one-line opening teaser for the game menu
- What is the setting in one or two sentences?

SECTION 2 — THE PLAYER:
- What is the player character's name?
- What is their background? (one or two sentences)
- What are 2-4 personality traits?

SECTION 3 — THE NARRATOR:
- Which model should the narrator use? (show the list)
- What tone should the narrator have? I'll write the narrator prompt for you based on your description

SECTION 4 — CHARACTERS (repeat for each):
- Character name
- Which model should this character use? (show the list)
- Describe their personality, how they talk, and their relationship to the player
- What location do they start in?
- What is their first line of dialogue?
- Starting mood (1-10)?
- Describe how this character behaves at each mood level from 1 to 10
- Any more characters? (if yes, repeat this section)

SECTION 5 — LOCATIONS (repeat for each):
- Location name (lowercase, underscores for spaces)
- Description of the location (what the player sees)
- What items can be found here? (these can be picked up by the player)
- Which characters are here? (use lowercase names matching the character keys)
- Any more locations? (if yes, repeat this section)

SECTION 6 — RULES:
- What is the win condition? (plain English, or leave blank for sandbox)
- What is the lose condition? (plain English, or leave blank)
- Are there any trigger words? (exact phrases that should produce specific responses, like "open door" → "The door is locked")

After all sections are complete, generate the full JSON file and nothing else.
```

---

## Engine tips (for stronger games)

- `**trigger_words**`: The engine checks whether each trigger string appears **anywhere** in the player’s message (substring). Prefer distinctive phrases (e.g. `examine crate`) over short strings or full location names, or moving there may fire the wrong response.
- `**win` / `lose`**: Write conditions the story can **show** clearly in a few turns (e.g. who agreed to what, who caught whom). The rules judge is conservative: ambiguous play continues.
- **Narrator**: Second person, no NPC dialogue in the narrator’s voice; end beats with a clear player prompt (e.g. “What do you do?”).
- **Checklist**: See `documents/GAME_DESIGN_CHECKLIST.md` before shipping a game JSON.

---

## After You Get the JSON

1. Save the output as a `.json` file in the `games/` folder
2. Use a lowercase filename with underscores (e.g. `haunted_mansion.json`)
3. **Validate without running the game** (catches wrong field names, bad references, missing `narrator.prompt`, etc.):
  ```bash
   python3 scripts/validate_game_json.py games/haunted_mansion.json
   # or every game:
   python3 scripts/validate_game_json.py --all
   # fail CI on warnings too:
   python3 scripts/validate_game_json.py --all --strict
  ```
4. Restart the Flask server or just start a new game — it reads from disk each time
5. Run `python3 play.py` and your new game will appear in the list

