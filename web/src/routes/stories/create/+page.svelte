<script lang="ts">
  import { goto } from "$app/navigation";
  import FieldAiAssist from "$lib/components/FieldAiAssist.svelte";

  const JSON_PLACEHOLDER = `{
  "title": "My Story",
  "opening": "The adventure begins...",
  "narrator": { "prompt": "You are the narrator..." },
  "player": { "name": "Hero", "background": "..." },
  "characters": {},
  "locations": {
    "start": {
      "description": "A room.",
      "items": [],
      "characters": []
    }
  },
  "rules": {}
}`;

  const GENRES = [
    "mystery",
    "thriller",
    "drama",
    "comedy",
    "sci-fi",
    "horror",
    "fantasy",
  ] as const;

  let createTab = $state<"build" | "json">("build");

  let title = $state("");
  let description = $state("");
  let genre = $state("");
  let gameJson = $state("");
  let clientMsg = $state<string | null>(null);
  let clientOk = $state(false);
  let serverError = $state<string | null>(null);
  let saving = $state(false);
  let buildError = $state<string | null>(null);

  let opening = $state("");
  let narratorStyle = $state("");
  let playerName = $state("");
  let playerBackground = $state("");
  let traits = $state("");
  let locationName = $state("");
  let locationDescription = $state("");
  let locationItems = $state("");
  let characterName = $state("");
  let characterPrompt = $state("");
  let characterFirstLine = $state("");
  let characterMood = $state(5);
  let charSectionOpen = $state(true);

  let aiConcept = $state("");
  let generating = $state(false);
  let genError = $state<string | null>(null);
  let aiGeneratedStory = $state<Record<string, unknown> | null>(null);

  function moodDescriptions(): Record<string, string> {
    const moodDescs: Record<string, string> = {};
    for (let i = 1; i <= 10; i++) {
      moodDescs[String(i)] = `Mood level ${i}/10.`;
    }
    return moodDescs;
  }

  function normalizeKey(s: string): string {
    return s.trim().toLowerCase().replace(/\s+/g, "_");
  }

  function mergeAiExtrasIntoGameJson(out: Record<string, unknown>): void {
    const ai = aiGeneratedStory;
    if (!ai) return;

    const locations = out.locations as Record<
      string,
      { description: string; items: string[]; characters: string[] }
    >;
    const characters = out.characters as Record<string, unknown>;

    const locArr = ai["locations"];
    if (Array.isArray(locArr) && locArr.length > 1) {
      for (let i = 1; i < locArr.length; i++) {
        const loc = locArr[i] as Record<string, unknown>;
        const k = normalizeKey(String(loc.key ?? ""));
        if (!k || locations[k]) continue;
        const items = Array.isArray(loc.items)
          ? (loc.items as unknown[]).map((x) => String(x))
          : [];
        locations[k] = {
          description: String(loc.description ?? ""),
          items,
          characters: [],
        };
      }
    }

    const charArr = ai["characters"];
    if (Array.isArray(charArr) && charArr.length > 1) {
      for (let j = 1; j < charArr.length; j++) {
        const ch = charArr[j] as Record<string, unknown>;
        const ck = normalizeKey(String(ch.key ?? ""));
        if (!ck || characters[ck]) continue;
        const moodN = Math.min(
          10,
          Math.max(1, Math.round(Number(ch.mood)) || 5)
        );
        const locRef = normalizeKey(String(ch.location ?? ""));
        characters[ck] = {
          model: "default",
          prompt:
            String(ch.personality ?? "").trim() ||
            `You are ${ck}. Stay in character. Reply in one or two short sentences.`,
          mood: moodN,
          mood_descriptions: moodDescriptions(),
          location: locRef,
          first_line: String(ch.first_line ?? "Hello.").trim() || "Hello.",
        };
        if (locations[locRef]) {
          const L = locations[locRef];
          if (!L.characters.includes(ck)) L.characters.push(ck);
        }
      }
    }
  }

  function buildGameJson(): Record<string, unknown> {
    const locationKey = locationName.trim().toLowerCase().replace(/\s+/g, "_");
    const charKey = characterName.trim().toLowerCase().replace(/\s+/g, "_");

    const narratorPrompt =
      narratorStyle.trim() ||
      "You are the narrator for a text adventure. Describe scenes in second person. Keep each response to 2-4 paragraphs. End each beat with: What do you do?";

    const playerTraits = traits.trim()
      ? traits
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean)
      : [];

    const locItems = locationItems.trim()
      ? locationItems
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean)
      : [];

    const characters: Record<string, unknown> = {};
    const locationCharacters: string[] = [];

    if (charKey) {
      const moodN = Math.min(
        10,
        Math.max(1, Math.round(Number(characterMood)) || 5)
      );

      characters[charKey] = {
        model: "default",
        prompt:
          characterPrompt.trim() ||
          `You are ${characterName.trim()}. Stay in character. Reply in one or two short sentences.`,
        mood: moodN,
        mood_descriptions: moodDescriptions(),
        location: locationKey,
        first_line: characterFirstLine.trim() || "Hello.",
      };
      locationCharacters.push(charKey);
    }

    const out: Record<string, unknown> = {
      title: title.trim(),
      opening: opening.trim(),
      description: description.trim(),
      genre: genre,
      narrator: {
        model: "default",
        prompt: narratorPrompt,
      },
      player: {
        name: playerName.trim() || "Adventurer",
        background:
          playerBackground.trim() || "A traveler in an unknown place.",
        traits: playerTraits,
      },
      characters,
      locations: {
        [locationKey]: {
          description: locationDescription.trim(),
          items: locItems,
          characters: locationCharacters,
        },
      },
      rules: {
        win: "",
        lose: "",
        trigger_words: {},
      },
    };
    mergeAiExtrasIntoGameJson(out);
    return out;
  }

  function applyAiStory(story: Record<string, unknown>) {
    aiGeneratedStory = story;
    title = String(story.title ?? "").trim();
    opening = String(story.opening ?? "").trim();
    description = String(story.description ?? "").trim();
    const g = String(story.genre ?? "")
      .trim()
      .toLowerCase();
    genre = GENRES.includes(g as (typeof GENRES)[number]) ? g : "";
    narratorStyle = String(story.narrator_prompt ?? "").trim();
    playerName = String(story.player_name ?? "").trim();
    playerBackground = String(story.player_background ?? "").trim();
    const pt = story.player_traits;
    traits = Array.isArray(pt) ? pt.map((x) => String(x)).join(", ") : "";

    const locs = story.locations;
    if (Array.isArray(locs) && locs.length > 0) {
      const L = locs[0] as Record<string, unknown>;
      locationName = String(L.key ?? "").trim();
      locationDescription = String(L.description ?? "").trim();
      const items = L.items;
      locationItems = Array.isArray(items)
        ? items.map((x) => String(x)).join(", ")
        : "";
    }

    const chs = story.characters;
    if (Array.isArray(chs) && chs.length > 0) {
      const C = chs[0] as Record<string, unknown>;
      characterName = String(C.key ?? "").trim();
      characterPrompt = String(C.personality ?? "").trim();
      characterFirstLine = String(C.first_line ?? "").trim();
      characterMood = Math.min(
        10,
        Math.max(1, Math.round(Number(C.mood)) || 5)
      );
      charSectionOpen = true;
    } else {
      characterName = "";
      characterPrompt = "";
      characterFirstLine = "";
      characterMood = 5;
      charSectionOpen = false;
    }
  }

  async function generateFromIdea() {
    genError = null;
    const c = aiConcept.trim();
    if (!c) return;
    generating = true;
    try {
      const r = await fetch("/api/generate-story", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ concept: c }),
      });
      const data = await r.json();
      if (!r.ok) {
        const msg =
          (data as { error?: string }).error ?? "Generation failed";
        const detail = (data as { detail?: string }).detail;
        genError = detail ? `${msg} (${detail})` : msg;
        return;
      }
      const story = (data as { story?: Record<string, unknown> }).story;
      if (!story || typeof story !== "object") {
        genError = "Invalid response from server.";
        return;
      }
      applyAiStory(story);
    } catch {
      genError = "Network error.";
    } finally {
      generating = false;
    }
  }

  function clearAiConcept() {
    aiConcept = "";
    genError = null;
    aiGeneratedStory = null;
  }

  function validateBuild(): boolean {
    buildError = null;
    if (!title.trim()) {
      buildError = "Title is required.";
      return false;
    }
    if (!opening.trim()) {
      buildError = "Opening is required.";
      return false;
    }
    if (!locationName.trim()) {
      buildError = "Location name is required.";
      return false;
    }
    if (!locationDescription.trim()) {
      buildError = "Location description is required.";
      return false;
    }
    return true;
  }

  async function createStoryFromBuild() {
    serverError = null;
    if (!validateBuild()) return;

    saving = true;
    try {
      const gameData = buildGameJson();
      const res = await fetch("/api/game-content", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || undefined,
          genre: genre.trim() || undefined,
          game_json: JSON.stringify(gameData),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        serverError =
          (data as { error?: string }).error ?? "Could not create story";
        return;
      }
      goto("/stories");
    } catch {
      serverError = "Network error";
    } finally {
      saving = false;
    }
  }

  function validateJson(
    titleInput: string,
    raw: string
  ): { ok: true; parsed: Record<string, unknown> } | { ok: false; error: string } {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      return {
        ok: false,
        error: e instanceof Error ? e.message : "Invalid JSON",
      };
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { ok: false, error: "JSON must be an object" };
    }
    const o = parsed as Record<string, unknown>;
    const locs = o.locations;
    if (
      typeof locs !== "object" ||
      locs === null ||
      Array.isArray(locs) ||
      Object.keys(locs as object).length === 0
    ) {
      return {
        ok: false,
        error: "JSON must include a non-empty 'locations' object",
      };
    }
    const t =
      titleInput.trim() ||
      (typeof o.title === "string" ? o.title.trim() : "");
    if (!t) {
      return {
        ok: false,
        error: "Title is required (form field or JSON 'title')",
      };
    }
    return { ok: true, parsed: o };
  }

  function validate() {
    serverError = null;
    const r = validateJson(title, gameJson);
    if (!r.ok) {
      clientOk = false;
      clientMsg = r.error;
      return false;
    }
    clientOk = true;
    clientMsg = "JSON looks valid.";
    return true;
  }

  async function createStory() {
    serverError = null;
    if (!validate()) return;

    const r = validateJson(title, gameJson);
    if (!r.ok) return;

    saving = true;
    try {
      const payloadTitle =
        title.trim() ||
        (typeof r.parsed.title === "string" ? r.parsed.title.trim() : "");
      const res = await fetch("/api/game-content", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: payloadTitle,
          description: description.trim() || undefined,
          genre: genre.trim() || undefined,
          game_json: gameJson,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        serverError =
          (data as { error?: string }).error ?? "Could not create story";
        return;
      }
      goto("/stories");
    } catch {
      serverError = "Network error";
    } finally {
      saving = false;
    }
  }

  function cancel() {
    goto("/stories");
  }
</script>

<main class="wrap">
  <header class="head">
    <h1>Create a Story</h1>
    <p class="sub">
      <strong>Build</strong> a minimal story with the guided form, or switch to
      <strong>Paste JSON</strong> for full control. Need help? Try the
      <a href="/tools/story-draft">story draft tool</a>
      or <code>GAME_DESIGN_PROMPT.md</code> in the repo.
    </p>
  </header>

  {#if serverError}
    <p class="err top-err">{serverError}</p>
  {/if}

  <div class="panel">
    <div class="create-tabs">
      <button
        type="button"
        class="create-tab"
        class:active={createTab === "build"}
        onclick={() => {
          createTab = "build";
          buildError = null;
        }}
      >
        Build
      </button>
      <button
        type="button"
        class="create-tab"
        class:active={createTab === "json"}
        onclick={() => {
          createTab = "json";
          buildError = null;
        }}
      >
        Paste JSON
      </button>
    </div>

    {#if createTab === "build"}
      <div class="ai-panel">
        <h3 class="ai-panel-title">Generate from an idea</h3>
        <textarea
          class="ai-concept-input"
          rows="4"
          maxlength="5000"
          bind:value={aiConcept}
          placeholder="A noir detective story set in a rainy 1940s city. The detective is investigating a missing person at a run-down hotel. There's a suspicious bellhop and a nervous hotel manager."
        ></textarea>
        <div class="ai-panel-actions">
          <button
            type="button"
            class="btn primary"
            disabled={generating || !aiConcept.trim()}
            onclick={() => generateFromIdea()}
          >
            Generate
          </button>
          <button
            type="button"
            class="btn ghost sm"
            disabled={generating}
            onclick={() => clearAiConcept()}
          >
            Clear
          </button>
        </div>
        {#if generating}
          <p class="gen-loading">
            Calling AI... this may take 10-30 seconds.
          </p>
        {/if}
        {#if genError}
          <p class="gen-err-sm">{genError}</p>
        {/if}
      </div>

      {#if buildError}
        <p class="err build-err">{buildError}</p>
      {/if}

      <form
        class="build-form"
        onsubmit={(e) => {
          e.preventDefault();
          createStoryFromBuild();
        }}
      >
        <section class="form-section">
          <h3 class="form-section-label">Story basics</h3>
          <label class="form-field">
            Title <span class="req">*</span>
            <input
              type="text"
              bind:value={title}
              placeholder="The Haunted Lighthouse"
              autocomplete="off"
            />
          </label>
          <label class="form-field">
            <span class="field-label-row">
              <span class="field-label-text"
                >Opening <span class="req">*</span></span
              >
              <FieldAiAssist
                bind:value={opening}
                field="opening"
                disabled={saving || generating}
              />
            </span>
            <textarea
              rows="3"
              bind:value={opening}
              placeholder="The adventure begins... (this is the first thing the player sees)"
            ></textarea>
          </label>
          <label class="form-field">
            <span class="field-label-row">
              <span class="field-label-text">Description</span>
              <FieldAiAssist
                bind:value={description}
                field="description"
                disabled={saving || generating}
              />
            </span>
            <input
              type="text"
              bind:value={description}
              placeholder="A short pitch for the story catalog"
              autocomplete="off"
            />
          </label>
          <label class="form-field">
            Genre
            <select bind:value={genre}>
              <option value="">—</option>
              {#each GENRES as g (g)}
                <option value={g}>{g}</option>
              {/each}
            </select>
          </label>
          <label class="form-field">
            <span class="field-label-row">
              <span class="field-label-text">Narrator style</span>
              <FieldAiAssist
                bind:value={narratorStyle}
                field="narrator_style"
                disabled={saving || generating}
              />
            </span>
            <textarea
              rows="2"
              bind:value={narratorStyle}
              placeholder="You are a noir narrator. Use second person. Keep scenes short and atmospheric. End each beat with: What do you do?"
            ></textarea>
          </label>
        </section>

        <section class="form-section">
          <h3 class="form-section-label">Your character</h3>
          <label class="form-field">
            Name
            <input
              type="text"
              bind:value={playerName}
              placeholder="Detective Cole"
              autocomplete="off"
            />
          </label>
          <label class="form-field">
            <span class="field-label-row">
              <span class="field-label-text">Background</span>
              <FieldAiAssist
                bind:value={playerBackground}
                field="player_background"
                disabled={saving || generating}
              />
            </span>
            <textarea
              rows="2"
              bind:value={playerBackground}
              placeholder="A burned-out PI hired for one last case."
            ></textarea>
          </label>
          <label class="form-field">
            Traits
            <input
              type="text"
              bind:value={traits}
              placeholder="cautious, observant, witty"
              autocomplete="off"
            />
          </label>
        </section>

        <section class="form-section">
          <h3 class="form-section-label">Starting location</h3>
          <label class="form-field">
            Location name <span class="req">*</span>
            <input
              type="text"
              bind:value={locationName}
              placeholder="the_office"
              autocomplete="off"
            />
            <span class="field-hint"
              >Use lowercase with underscores (e.g., dark_alley, throne_room)</span
            >
          </label>
          <label class="form-field">
            <span class="field-label-row">
              <span class="field-label-text"
                >Description <span class="req">*</span></span
              >
              <FieldAiAssist
                bind:value={locationDescription}
                field="location_description"
                disabled={saving || generating}
              />
            </span>
            <textarea
              rows="3"
              bind:value={locationDescription}
              placeholder="A cramped office with a desk, a rotary phone, and stacks of cold case files."
            ></textarea>
          </label>
          <label class="form-field">
            Items
            <input
              type="text"
              bind:value={locationItems}
              placeholder="flashlight, old map, rusty key"
              autocomplete="off"
            />
          </label>
        </section>

        <section class="form-section">
          <button
            type="button"
            class="collapse-header"
            onclick={() => (charSectionOpen = !charSectionOpen)}
          >
            <span class="collapse-arrow" class:open={charSectionOpen}>▶</span>
            First character (optional)
          </button>
          {#if charSectionOpen}
            <label class="form-field">
              Character name
              <input
                type="text"
                bind:value={characterName}
                placeholder="secretary"
                autocomplete="off"
              />
              <span class="field-hint">Use lowercase with underscores</span>
            </label>
            <label class="form-field">
              <span class="field-label-row">
                <span class="field-label-text">Personality prompt</span>
                <FieldAiAssist
                  bind:value={characterPrompt}
                  field="character_prompt"
                  disabled={saving || generating}
                />
              </span>
              <textarea
                rows="2"
                bind:value={characterPrompt}
                placeholder="Sharp-tongued but loyal. Knows more than she lets on. Speaks in short, clipped sentences."
              ></textarea>
            </label>
            <label class="form-field">
              <span class="field-label-row">
                <span class="field-label-text">First line</span>
                <FieldAiAssist
                  bind:value={characterFirstLine}
                  field="character_first_line"
                  disabled={saving || generating}
                />
              </span>
              <input
                type="text"
                bind:value={characterFirstLine}
                placeholder="You look terrible. Coffee?"
                autocomplete="off"
              />
            </label>
            <label class="form-field">
              Starting mood
              <input
                type="number"
                min="1"
                max="10"
                bind:value={characterMood}
              />
            </label>
          {/if}
        </section>

        {#if aiGeneratedStory}
          {@const locsRaw = aiGeneratedStory["locations"]}
          {@const chsRaw = aiGeneratedStory["characters"]}
          {@const nL = Array.isArray(locsRaw) ? locsRaw.length : 0}
          {@const nC = Array.isArray(chsRaw) ? chsRaw.length : 0}
          {#if nL > 1 || nC > 1}
            <p class="ai-extras-notice">
              AI generated {nL}
              {nL === 1 ? "location" : "locations"} and {nC}
              {nC === 1 ? "character" : "characters"}. The form shows the first
              of each — all will be included when you create the story.
            </p>
          {/if}
        {/if}

        <div class="btn-row">
          <button type="submit" class="btn primary" disabled={saving}>
            {saving ? "Creating…" : "Create Story"}
          </button>
          <button type="button" class="btn ghost" onclick={cancel}>Cancel</button>
        </div>
      </form>
    {:else}
      <form
        class="json-form"
        onsubmit={(e) => {
          e.preventDefault();
          createStory();
        }}
      >
        <label class="field">
          Title <span class="req">*</span>
          <input type="text" class="inp" bind:value={title} autocomplete="off" />
        </label>

        <label class="field">
          Description
          <input
            type="text"
            class="inp"
            bind:value={description}
            placeholder="A short pitch for your story"
            autocomplete="off"
          />
        </label>

        <label class="field">
          Genre
          <select class="select" bind:value={genre}>
            <option value="">—</option>
            {#each GENRES as g (g)}
              <option value={g}>{g}</option>
            {/each}
          </select>
        </label>

        <label class="field">
          Game JSON <span class="req">*</span>
          <textarea
            class="textarea"
            rows="16"
            bind:value={gameJson}
            placeholder={JSON_PLACEHOLDER}
          ></textarea>
        </label>

        {#if clientMsg}
          <p class:ok={clientOk} class:bad={!clientOk} class="client-msg">
            {clientMsg}
          </p>
        {/if}

        <div class="btn-row">
          <button type="button" class="btn" onclick={() => validate()}>
            Validate
          </button>
          <button type="submit" class="btn primary" disabled={saving}>
            {saving ? "Creating…" : "Create Story"}
          </button>
          <button type="button" class="btn ghost" onclick={cancel}>Cancel</button>
        </div>
      </form>
    {/if}
  </div>
</main>

<style>
  .wrap {
    max-width: 54rem;
    margin: 0 auto;
    padding: 1.25rem 1rem 3rem;
    background: #0f1114;
    min-height: calc(100vh - 42px);
    box-sizing: border-box;
  }
  .head h1 {
    margin: 0 0 0.35rem;
    font-size: 1.35rem;
    color: #e8eaed;
  }
  .sub {
    margin: 0;
    color: #9aa0a6;
    font-size: 0.9rem;
    line-height: 1.5;
  }
  .sub a {
    color: #8ab4f8;
  }
  .sub code {
    font-size: 0.82rem;
    color: #bdc1c6;
  }
  .sub strong {
    color: #bdc1c6;
    font-weight: 600;
  }
  .top-err {
    margin: 0.5rem 0 0;
  }
  .build-err {
    margin: 0 0 1rem;
  }
  .panel {
    margin-top: 1rem;
    padding: 1.25rem;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    border-radius: 10px;
  }

  .create-tabs {
    display: flex;
    border-bottom: 1px solid #2a2f38;
    margin-bottom: 1.25rem;
  }
  .create-tab {
    flex: 1;
    max-width: 10rem;
    padding: 0.6rem 0.5rem;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: #9aa0a6;
    font-size: 0.85rem;
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s;
  }
  .create-tab:hover {
    color: #e8eaed;
  }
  .create-tab.active {
    color: #8ab4f8;
    border-bottom-color: #8ab4f8;
  }

  .ai-panel {
    background: #13151a;
    border: 1px solid #2a2f38;
    border-radius: 10px;
    padding: 1rem 1.1rem;
    margin-bottom: 1.25rem;
  }
  .ai-panel-title {
    margin: 0 0 0.65rem;
    font-size: 0.85rem;
    font-weight: 600;
    color: #e8eaed;
  }
  .ai-concept-input {
    display: block;
    width: 100%;
    box-sizing: border-box;
    padding: 0.5rem 0.65rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    font-family: inherit;
    font-size: 0.9rem;
    line-height: 1.45;
    resize: vertical;
  }
  .ai-panel-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.65rem;
    align-items: center;
  }
  .gen-loading {
    margin: 0.65rem 0 0;
    font-size: 0.85rem;
    color: #8ab4f8;
  }
  .gen-err-sm {
    margin: 0.5rem 0 0;
    font-size: 0.85rem;
    color: #f28b82;
  }
  .ai-extras-notice {
    margin: 0 0 1rem;
    padding: 0.65rem 0.75rem;
    font-size: 0.85rem;
    line-height: 1.45;
    color: #bdc1c6;
    background: rgba(138, 180, 248, 0.12);
    border: 1px solid rgba(138, 180, 248, 0.25);
    border-radius: 8px;
  }

  .form-section {
    margin-top: 1.5rem;
  }
  .form-section:first-of-type {
    margin-top: 0;
  }
  .form-section-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #9aa0a6;
    margin: 0 0 0.75rem;
  }
  .field-label-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.35rem 0.75rem;
    margin-bottom: 0.3rem;
  }
  .field-label-text {
    flex: 1;
    min-width: 8rem;
    font-size: 0.85rem;
    color: #9aa0a6;
  }
  .form-field {
    display: block;
    margin-bottom: 0.85rem;
    font-size: 0.85rem;
    color: #9aa0a6;
  }
  .form-field input,
  .form-field textarea,
  .form-field select {
    display: block;
    width: 100%;
    box-sizing: border-box;
    margin-top: 0.3rem;
    padding: 0.5rem 0.65rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    font-family: inherit;
    font-size: 0.9rem;
  }
  .form-field textarea {
    resize: vertical;
  }
  .field-hint {
    display: block;
    margin-top: 0.25rem;
    font-size: 0.75rem;
    color: #9aa0a6;
  }

  .collapse-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: none;
    border: none;
    color: #9aa0a6;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    cursor: pointer;
    padding: 0;
    margin: 0 0 0.75rem;
  }
  .collapse-arrow {
    transition: transform 0.15s;
    font-size: 0.6rem;
    display: inline-block;
  }
  .collapse-arrow.open {
    transform: rotate(90deg);
  }

  .field {
    display: block;
    margin-bottom: 1rem;
    font-size: 0.85rem;
    color: #9aa0a6;
  }
  .req {
    color: #f28b82;
  }
  .inp,
  .select,
  .textarea {
    display: block;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    margin-top: 0.35rem;
    padding: 0.5rem 0.65rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    font-family: inherit;
    font-size: 0.9rem;
  }
  .textarea {
    font-family: ui-monospace, monospace;
    font-size: 0.82rem;
    line-height: 1.4;
    resize: vertical;
  }
  .client-msg {
    margin: 0 0 1rem;
    font-size: 0.88rem;
  }
  .client-msg.ok {
    color: #81c995;
  }
  .client-msg.bad {
    color: #f28b82;
  }
  .btn-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: center;
    margin-top: 1.5rem;
  }
  .btn {
    cursor: pointer;
    border: 1px solid #3c4043;
    background: #2a2f38;
    color: #e8eaed;
    padding: 0.45rem 0.9rem;
    border-radius: 8px;
    font-size: 0.9rem;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn.sm {
    padding: 0.35rem 0.65rem;
    font-size: 0.8rem;
  }
  .btn.primary {
    background: #1a73e8;
    border-color: #1a73e8;
  }
  .btn.ghost {
    background: transparent;
  }
  .err {
    color: #f28b82;
    font-size: 0.9rem;
  }
</style>
