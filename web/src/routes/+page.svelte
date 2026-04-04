<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";

  type Game = { file: string; title: string; opening?: string };

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
  let newName = $state("");
  let pickedGame = $state<string>("");

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
      if (games.length && !pickedGame) pickedGame = games[0].file;
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

  async function startAdventure() {
    if (!pickedGame) {
      advError = "Pick a game.";
      return;
    }
    busy = true;
    advError = null;
    try {
      const body: { game_file: string; name?: string } = {
        game_file: pickedGame,
      };
      const n = newName.trim();
      if (n) body.name = n;

      const r = await fetch("/api/adventures", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
      newName = "";
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
    <h1>Your Adventures</h1>
    <p class="sub">
      Continue a saved run or start a new one. Slot management is on the
      <a href="/play">Play</a> page. <a href="/tools">Tools</a> stay available without signing in.
    </p>
  </header>

  {#if advError}
    <p class="err">{advError}</p>
  {/if}

  <section class="panel">
    <div class="panel-head">
      <h2>Adventures</h2>
      <button type="button" class="btn sm ghost" onclick={() => loadAdventures()}>
        Refresh
      </button>
    </div>

    {#if adventures.length === 0}
      <p class="muted">No adventures yet. Start one below.</p>
    {:else}
      <ul class="adv-list">
        {#each adventures as a (a.id)}
          <li class="adv">
            <div class="meta">
              <strong>{a.name}</strong>
              <span class="file">{a.game_file}.json</span>
              <span class="when">Last played {formatRelative(a.last_played)}</span>
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
    {/if}
  </section>

  <section class="panel">
    <h2>Start new adventure</h2>
    {#if loadError}
      <p class="err">{loadError}</p>
      <button type="button" class="btn" onclick={loadGames}>Retry</button>
    {:else if games.length === 0 && !loadError}
      <p class="muted">Loading games…</p>
    {:else}
      <label class="field">
        Game
        <select class="select" bind:value={pickedGame}>
          {#each games as g (g.file)}
            <option value={g.file}>{g.title} ({g.file}.json)</option>
          {/each}
        </select>
      </label>
      <label class="field">
        Adventure name (optional)
        <input
          type="text"
          class="inp"
          placeholder="Defaults to game title"
          bind:value={newName}
        />
      </label>
      <button
        type="button"
        class="btn primary"
        disabled={busy || !pickedGame}
        onclick={startAdventure}
      >
        {busy ? "Starting…" : "Start"}
      </button>
    {/if}
  </section>
</main>

<style>
  .wrap {
    max-width: 42rem;
    margin: 0 auto;
    padding: 1.25rem 1rem 3rem;
  }
  .head h1 {
    margin: 0 0 0.35rem;
    font-size: 1.35rem;
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
  .panel h2 {
    margin: 0 0 0.75rem;
    font-size: 1.05rem;
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
    padding: 0.85rem 0;
    border-bottom: 1px solid #2a2f38;
  }
  .adv:last-child {
    border-bottom: none;
  }
  .meta strong {
    display: block;
    color: #e8eaed;
    font-size: 1rem;
  }
  .file {
    display: block;
    font-size: 0.8rem;
    color: #9aa0a6;
    margin-top: 0.2rem;
  }
  .when {
    display: block;
    font-size: 0.78rem;
    color: #9aa0a6;
    margin-top: 0.25rem;
  }
  .adv-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .field {
    display: block;
    margin-bottom: 0.75rem;
    font-size: 0.85rem;
    color: #9aa0a6;
  }
  .inp {
    display: block;
    width: 100%;
    max-width: 22rem;
    box-sizing: border-box;
    margin-top: 0.35rem;
    padding: 0.45rem 0.55rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
  }
  .select {
    display: block;
    margin-top: 0.35rem;
    padding: 0.4rem 0.55rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    font-size: 0.9rem;
    max-width: 100%;
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
