<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { get } from "svelte/store";
  import { page } from "$app/stores";

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

  type MyStory = {
    id: number;
    title: string;
    description: string | null;
    genre: string | null;
  };

  let storyId = $state<number | null>(null);
  let notFound = $state(false);
  let title = $state("");
  let description = $state("");
  let genre = $state("");
  let gameJson = $state("");
  let clientMsg = $state<string | null>(null);
  let clientOk = $state(false);
  let serverError = $state<string | null>(null);
  let saving = $state(false);
  let loading = $state(true);

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
    const raw = gameJson.trim();
    if (!raw) {
      if (!title.trim()) {
        clientOk = false;
        clientMsg = "Title is required.";
        return false;
      }
      clientOk = true;
      clientMsg =
        "Metadata OK. Leave JSON empty to keep the saved story on the server, or paste JSON to replace it.";
      return true;
    }
    const r = validateJson(title, raw);
    if (!r.ok) {
      clientOk = false;
      clientMsg = r.error;
      return false;
    }
    clientOk = true;
    clientMsg = "JSON looks valid.";
    return true;
  }

  async function loadStory() {
    const raw = get(page).params.id;
    const id = parseInt(raw ?? "", 10);
    if (Number.isNaN(id)) {
      notFound = true;
      loading = false;
      return;
    }
    storyId = id;
    loading = true;
    notFound = false;
    serverError = null;
    try {
      const r = await fetch(`/api/game-content/${id}`, { credentials: "include" });
      const data = await r.json();
      if (!r.ok) {
        serverError =
          (data as { error?: string }).error ?? "Story not found";
        notFound = true;
        return;
      }
      const s = data as { title?: string; description?: string; genre?: string; game_json?: string };
      title = s.title ?? "";
      description = (s.description ?? "").trim();
      genre = (s.genre ?? "").trim();
      if (s.game_json) {
        try {
          gameJson = JSON.stringify(JSON.parse(s.game_json), null, 2);
        } catch {
          gameJson = s.game_json;
        }
      } else {
        gameJson = "";
      }
    } catch {
      serverError = "Network error";
      notFound = true;
    } finally {
      loading = false;
    }
  }

  async function saveStory() {
    if (storyId == null) return;
    serverError = null;
    if (!validate()) return;

    const rawJson = gameJson.trim();
    let payloadTitle = title.trim();
    if (rawJson) {
      const r = validateJson(title, rawJson);
      if (!r.ok) return;
      payloadTitle =
        title.trim() ||
        (typeof r.parsed.title === "string" ? r.parsed.title.trim() : "");
    } else if (!payloadTitle) {
      serverError = "Title is required.";
      return;
    }

    saving = true;
    try {
      const body: Record<string, string> = {
        title: payloadTitle,
        description: description.trim(),
        genre: genre.trim(),
      };
      if (rawJson) {
        body.game_json = rawJson;
      }
      const res = await fetch(`/api/game-content/${storyId}`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        serverError =
          (data as { error?: string }).error ?? "Could not save story";
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

  onMount(() => {
    void loadStory();
  });
</script>

<main class="wrap">
  {#if loading}
    <p class="muted">Loading…</p>
  {:else if notFound}
    <header class="head">
      <h1>Story not found</h1>
      <p class="sub">
        <a href="/stories">Back to My Stories</a>
      </p>
    </header>
  {:else}
    <header class="head">
      <h1>Edit Story</h1>
      <p class="sub">
        Update title, description, and genre anytime. The story list API does not
        return saved JSON — leave the JSON field empty to keep your current game
        on the server, or paste a full JSON document to replace it. Validate
        before saving when pasting.
        <a href="/tools/story-draft">Story draft tool</a>
      </p>
    </header>

    {#if serverError}
      <p class="err top-err">{serverError}</p>
    {/if}

    <form
      class="panel"
      onsubmit={(e) => {
        e.preventDefault();
        saveStory();
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
          {saving ? "Saving…" : "Save Changes"}
        </button>
        <button type="button" class="btn ghost" onclick={cancel}>Cancel</button>
      </div>
    </form>
  {/if}
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
  .top-err {
    margin: 0.5rem 0 0;
  }
  .panel {
    margin-top: 1rem;
    padding: 1.25rem;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    border-radius: 10px;
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
  .muted {
    color: #9aa0a6;
    font-size: 0.9rem;
  }
</style>
