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

  type GraphMeta = {
    name: string;
    description: string;
    node_count: number;
  };

  let storyId = $state<number | null>(null);
  let notFound = $state(false);
  let title = $state("");
  let description = $state("");
  let genre = $state("");
  let graphType = $state("standard");
  let graphTypes = $state<GraphMeta[]>([]);
  /** From last loaded JSON; edit JSON to change — not live-synced while typing. */
  let socialGuideDisplay = $state("");
  let socialMilestonesLines = $state<string[]>([]);
  let gameJson = $state("");
  let clientMsg = $state<string | null>(null);
  let clientOk = $state(false);
  let serverError = $state<string | null>(null);
  let saving = $state(false);
  let loading = $state(true);

  function graphTypeLabel(name: string): string {
    return name
      .split(/[_\s]+/)
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(" ");
  }

  function resolveGraphType(gt: string): string {
    const g = gt.trim().toLowerCase();
    if (graphTypes.length > 0) {
      if (graphTypes.some((x) => x.name === g)) return g;
      if (g === "social" && graphTypes.some((x) => x.name === "social"))
        return "social";
      if (graphTypes.some((x) => x.name === "standard")) return "standard";
      return graphTypes[0].name;
    }
    return g === "social" ? "social" : "standard";
  }

  const selectedGraphDescription = $derived.by(() => {
    const meta = graphTypes.find((x) => x.name === graphType);
    return (meta?.description ?? "").trim();
  });

  async function loadGraphTypes() {
    try {
      const r = await fetch("/api/graphs", { credentials: "include" });
      if (!r.ok) return;
      const data = await r.json();
      graphTypes = Array.isArray(data) ? data : [];
      if (
        graphTypes.length > 0 &&
        !graphTypes.some((x) => x.name === graphType)
      ) {
        graphType = graphTypes.some((x) => x.name === "standard")
          ? "standard"
          : graphTypes[0].name;
      }
    } catch {
      /* ignore */
    }
  }

  function patchGameJsonGraphType() {
    const raw = gameJson.trim();
    if (!raw) {
      applyGraphContextFromParsed({
        graph_type: graphType,
        ...(graphType === "social"
          ? {
              guide: socialGuideDisplay,
              milestones: socialMilestonesLines,
            }
          : {}),
      } as Record<string, unknown>);
      return;
    }
    try {
      const o = JSON.parse(raw) as Record<string, unknown>;
      o.graph_type = graphType;
      gameJson = JSON.stringify(o, null, 2);
      applyGraphContextFromParsed(o);
    } catch {
      /* invalid JSON — graphType still updated for labels */
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

  function applyGraphContextFromParsed(parsed: Record<string, unknown>) {
    const raw = String(parsed.graph_type ?? "standard").trim().toLowerCase();
    graphType = resolveGraphType(raw);
    if (graphType === "social") {
      socialGuideDisplay = String(parsed.guide ?? "").trim();
      const m = parsed.milestones;
      socialMilestonesLines = Array.isArray(m)
        ? (m as unknown[]).map((x) => String(x).trim()).filter(Boolean)
        : [];
    } else {
      socialGuideDisplay = "";
      socialMilestonesLines = [];
    }
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
          const parsed = JSON.parse(s.game_json) as Record<string, unknown>;
          gameJson = JSON.stringify(parsed, null, 2);
          applyGraphContextFromParsed(parsed);
        } catch {
          gameJson = s.game_json;
          graphType = "standard";
          socialGuideDisplay = "";
          socialMilestonesLines = [];
        }
      } else {
        gameJson = "";
        graphType = "standard";
        socialGuideDisplay = "";
        socialMilestonesLines = [];
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

  onMount(async () => {
    await loadGraphTypes();
    await loadStory();
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

      <div class="field graph-meta-block">
        <label class="graph-meta-label" for="story-graph-type">Story type</label>
        <select
          id="story-graph-type"
          class="select graph-type-select"
          value={graphType}
          onchange={(e) => {
            graphType = (e.currentTarget as HTMLSelectElement).value;
            patchGameJsonGraphType();
          }}
        >
          {#if graphTypes.length === 0}
            <option value="standard">Standard</option>
            <option value="social">Social</option>
          {:else}
            {#each graphTypes as gt (gt.name)}
              <option value={gt.name}>{graphTypeLabel(gt.name)}</option>
            {/each}
          {/if}
        </select>
        <p class="graph-meta-hint">
          {#if selectedGraphDescription}
            {selectedGraphDescription}
          {:else if graphTypes.length === 0}
            Shown from JSON as loaded. To change type or social fields, edit
            <code>graph_type</code>, <code>guide</code>, and
            <code>milestones</code> in the textarea below, then save.
          {:else}
            Select a pipeline template. When the JSON below is valid,
            <code>graph_type</code> updates automatically.
          {/if}
        </p>
        <p class="graph-meta-hint graph-meta-hint-secondary">
          For <code>guide</code> and <code>milestones</code>, edit the JSON textarea
          (social stories).
        </p>
        {#if graphType === "social"}
          <div class="social-readonly-summary">
            <p class="social-summary-line">
              <span class="social-summary-k">Guide NPC</span>
              <span class="social-summary-v"
                >{socialGuideDisplay || "—"}</span
              >
            </p>
            <p class="social-summary-k social-milestones-heading">Milestones</p>
            {#if socialMilestonesLines.length === 0}
              <p class="social-summary-empty">None in JSON</p>
            {:else}
              <ol class="social-milestones-list">
                {#each socialMilestonesLines as line, i (i)}
                  <li>{line}</li>
                {/each}
              </ol>
            {/if}
          </div>
        {/if}
      </div>

      <p class="helper-text">
        Paste a full game JSON to replace the current story data, or leave empty
        to keep what&apos;s already saved. Validate before saving to catch
        formatting errors.
      </p>

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

  .helper-text {
    margin: 0 0 0.85rem;
    color: #9aa0a6;
    font-size: 0.82rem;
    line-height: 1.45;
  }

  .graph-meta-block {
    margin-bottom: 1rem;
  }
  .graph-meta-label {
    display: block;
    font-size: 0.85rem;
    color: #9aa0a6;
    margin-bottom: 0.35rem;
  }
  .graph-type-select {
    display: block;
    max-width: 22rem;
    margin-top: 0.15rem;
  }
  .graph-meta-hint {
    margin: 0.5rem 0 0;
    font-size: 0.75rem;
    line-height: 1.45;
    color: #80868b;
  }
  .graph-meta-hint-secondary {
    margin: 0.35rem 0 0;
    font-size: 0.72rem;
    color: #6f747a;
  }
  .graph-meta-hint code {
    font-size: 0.72rem;
    padding: 0.05rem 0.25rem;
    border-radius: 4px;
    background: #0f1114;
    color: #bdc1c6;
  }
  .social-readonly-summary {
    margin-top: 0.75rem;
    padding: 0.65rem 0.75rem;
    border-radius: 8px;
    border: 1px solid #2a2f38;
    background: rgba(255, 255, 255, 0.03);
  }
  .social-summary-line {
    margin: 0 0 0.5rem;
    font-size: 0.82rem;
    line-height: 1.4;
    color: #bdc1c6;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 0.6rem;
    align-items: baseline;
  }
  .social-summary-k {
    font-weight: 600;
    color: #9aa0a6;
    min-width: 5.5rem;
  }
  .social-summary-v {
    color: #e8eaed;
    word-break: break-word;
  }
  .social-milestones-heading {
    margin: 0.35rem 0 0.35rem;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .social-summary-empty {
    margin: 0;
    font-size: 0.8rem;
    color: #80868b;
    font-style: italic;
  }
  .social-milestones-list {
    margin: 0;
    padding-left: 1.15rem;
    font-size: 0.8rem;
    line-height: 1.45;
    color: #bdc1c6;
  }
  .social-milestones-list li {
    margin-bottom: 0.2rem;
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
