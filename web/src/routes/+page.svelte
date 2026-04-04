<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";

  type Game = {
    file: string;
    title: string;
    opening?: string;
    description?: string;
    genre?: string;
  };

  type Adventure = {
    id: number;
    game_file: string;
    name: string;
    last_played: string | null;
    created_at: string;
  };

  let games = $state<Game[]>([]);
  let adventures = $state<Adventure[]>([]);
  let loadError = $state<string | null>(null);
  let advError = $state<string | null>(null);
  let busy = $state(false);

  function formatRelative(iso: string | null): string {
    if (!iso) return "—";
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return iso;
    const diffSec = Math.round((Date.now() - t) / 1000);
    const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
    if (Math.abs(diffSec) < 60) return rtf.format(-diffSec, "second");
    const diffMin = Math.round(diffSec / 60);
    if (Math.abs(diffMin) < 60) return rtf.format(-diffMin, "minute");
    const diffHr = Math.round(diffMin / 60);
    if (Math.abs(diffHr) < 48) return rtf.format(-diffHr, "hour");
    const diffDay = Math.round(diffHr / 24);
    return rtf.format(-diffDay, "day");
  }

  function genrePillClass(genre: string | undefined): string {
    const g = (genre ?? "").trim().toLowerCase();
    const allowed = new Set([
      "mystery",
      "thriller",
      "drama",
      "comedy",
      "sci-fi",
      "horror",
      "fantasy",
    ]);
    if (!allowed.has(g)) return "genre-pill genre-unknown";
    return `genre-pill genre-${g.replace(/\s+/g, "-")}`;
  }

  async function loadGames() {
    loadError = null;
    try {
      const r = await fetch("/api/games", { credentials: "include" });
      const data = await r.json();
      if (!r.ok) {
        loadError =
          (data as { error?: string }).error ?? "Failed to load games";
        return;
      }
      games = (data as { games?: Game[] }).games ?? [];
    } catch {
      loadError = "Could not reach the server.";
    }
  }

  async function loadAdventures() {
    advError = null;
    try {
      const r = await fetch("/api/adventures", { credentials: "include" });
      const data = await r.json();
      if (!r.ok) {
        advError =
          (data as { error?: string }).error ?? "Failed to load adventures";
        return;
      }
      adventures = (data as { adventures?: Adventure[] }).adventures ?? [];
    } catch {
      advError = "Could not load adventures.";
    }
  }

  async function refreshAll() {
    await Promise.all([loadGames(), loadAdventures()]);
  }

  function goPlay(id: number) {
    goto(`/play?adventure=${id}`);
  }

  async function deleteAdventure(a: Adventure, e: Event) {
    e.stopPropagation();
    if (
      !confirm(
        `Delete adventure “${a.name}”? All saves for it will be removed.`
      )
    ) {
      return;
    }
    busy = true;
    advError = null;
    try {
      const r = await fetch(`/api/adventures/${a.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!r.ok) {
        const d = await r.json();
        advError = (d as { error?: string }).error ?? "Delete failed";
        return;
      }
      await loadAdventures();
    } catch {
      advError = "Delete request failed";
    } finally {
      busy = false;
    }
  }

  async function startAdventureWithGame(gameFile: string) {
    busy = true;
    advError = null;
    try {
      const r = await fetch("/api/adventures", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_file: gameFile }),
      });
      const data = await r.json();
      if (!r.ok) {
        advError = (data as { error?: string }).error ?? "Start failed";
        return;
      }
      const adv = (data as { adventure?: { id: number } }).adventure;
      const id = adv?.id;
      if (id == null) {
        advError = "Invalid response";
        return;
      }
      await loadAdventures();
      goPlay(id);
    } catch {
      advError = "Start request failed";
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    refreshAll();
  });
</script>

<main class="wrap">
  <header class="head">
    <h1>Lobby</h1>
    <p class="sub">
      Resume saved runs, browse the story catalog, or open the tools to draft or
      validate JSON. Slot management lives on the
      <a href="/play">Play</a> page. <a href="/tools">Tools</a> are available
      without signing in.
    </p>
  </header>

  {#if advError}
    <p class="err">{advError}</p>
  {/if}

  {#if adventures.length > 0}
    <section class="panel section-adventures">
      <div class="panel-head">
        <h2>Your Adventures</h2>
        <button
          type="button"
          class="btn sm ghost"
          onclick={() => loadAdventures()}
        >
          Refresh
        </button>
      </div>

      <ul class="adv-list">
        {#each adventures as a (a.id)}
          <li class="adv">
            <div class="meta">
              <strong class="adv-name">{a.name}</strong>
              <span class="file">{a.game_file}.json</span>
              <span class="when"
                >Last played {formatRelative(a.last_played)}</span>
            </div>
            <div class="adv-actions">
              <button
                type="button"
                class="btn primary"
                disabled={busy}
                onclick={() => goPlay(a.id)}
              >
                Continue
              </button>
              <button
                type="button"
                class="btn danger sm"
                disabled={busy}
                onclick={(e) => deleteAdventure(a, e)}
              >
                Delete
              </button>
            </div>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <section class="panel section-catalog">
    <h2 class="section-title">Story Catalog</h2>
    {#if loadError}
      <p class="err">{loadError}</p>
      <button type="button" class="btn" onclick={loadGames}>Retry</button>
    {:else if games.length === 0 && !loadError}
      <p class="muted">Loading games…</p>
    {:else}
      <div class="catalog-grid">
        {#each games as g (g.file)}
          <article class="story-card">
            <span class={genrePillClass(g.genre)}>
              {(g.genre ?? "").trim().replace(/-/g, " ") || "story"}
            </span>
            <h3 class="card-title">{g.title}</h3>
            <p class="card-desc">
              {g.description?.trim() ||
                "No description yet — dive in and see what happens."}
            </p>
            <button
              type="button"
              class="btn primary card-play"
              disabled={busy}
              onclick={() => startAdventureWithGame(g.file)}
            >
              {busy ? "Starting…" : "Play"}
            </button>
          </article>
        {/each}
      </div>
    {/if}
  </section>

  <section class="panel section-create">
    <h2 class="section-title">Create Your Own Story</h2>
    <p class="create-blurb">
      Build a custom game from a story outline or paste your own game JSON.
    </p>
    <div class="create-actions">
      <a href="/tools/story-draft" class="btn primary link-btn"
        >Story Draft Tool</a
      >
      <a href="/tools/validate" class="btn link-btn">Validate Game JSON</a>
    </div>
  </section>
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
  .panel {
    margin-top: 1.25rem;
    padding: 1rem 1.25rem;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    border-radius: 10px;
  }
  .section-title {
    margin: 0 0 1rem;
    font-size: 1.05rem;
    color: #e8eaed;
  }
  .panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }
  .panel-head h2 {
    margin: 0;
    font-size: 1.05rem;
    color: #e8eaed;
  }
  .adv-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .adv {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 1rem 0.85rem;
    margin: 0 -0.85rem;
    border-radius: 8px;
    border-bottom: 1px solid #2a2f38;
  }
  .adv:last-child {
    border-bottom: none;
    padding-bottom: 0.25rem;
  }
  .adv:first-child {
    padding-top: 0.25rem;
  }
  .adv-name {
    display: block;
    color: #e8eaed;
    font-size: 1.02rem;
    font-weight: 600;
  }
  .file {
    display: block;
    font-size: 0.8rem;
    color: #9aa0a6;
    margin-top: 0.25rem;
  }
  .when {
    display: block;
    font-size: 0.78rem;
    color: #9aa0a6;
    margin-top: 0.3rem;
  }
  .adv-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }

  .catalog-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
    gap: 1rem;
  }
  .story-card {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    border-radius: 10px;
    padding: 1rem 1.1rem 1.1rem;
    min-height: 11rem;
  }
  .genre-pill {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    font-size: 0.7rem;
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.04em;
    margin-bottom: 0.55rem;
  }
  .genre-pill.genre-mystery {
    background: #8ab4f8;
    color: #0f1114;
  }
  .genre-pill.genre-thriller,
  .genre-pill.genre-horror {
    background: #f28b82;
    color: #0f1114;
  }
  .genre-pill.genre-drama,
  .genre-pill.genre-fantasy {
    background: #c58af9;
    color: #0f1114;
  }
  .genre-pill.genre-comedy {
    background: #fdd663;
    color: #0f1114;
  }
  .genre-pill.genre-sci-fi {
    background: #81c995;
    color: #0f1114;
  }
  .genre-pill.genre-unknown {
    background: #2a2f38;
    color: #9aa0a6;
  }
  .card-title {
    margin: 0 0 0.45rem;
    font-size: 1.08rem;
    font-weight: 600;
    color: #e8eaed;
    line-height: 1.25;
  }
  .card-desc {
    margin: 0;
    flex: 1;
    font-size: 0.85rem;
    line-height: 1.45;
    color: #9aa0a6;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .card-play {
    margin-top: 1rem;
    width: 100%;
  }

  .create-blurb {
    margin: 0 0 1rem;
    font-size: 0.9rem;
    color: #9aa0a6;
    line-height: 1.5;
  }
  .create-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }
  .link-btn {
    display: inline-block;
    text-decoration: none;
    text-align: center;
    box-sizing: border-box;
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
  .btn.sm {
    padding: 0.35rem 0.65rem;
    font-size: 0.8rem;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn.primary {
    background: #1a73e8;
    border-color: #1a73e8;
  }
  .btn.danger {
    border-color: #c5221f;
    color: #f28b82;
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
