<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { authState } from "$lib/auth.svelte";

  type CommunityStory = {
    id: number;
    title: string;
    description: string | null;
    genre: string | null;
    play_count: number;
    author: string;
    original_author: string;
    is_global: boolean;
    created_at: string;
  };

  let stories = $state<CommunityStory[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);
  let busy = $state(false);

  function genrePillClass(genre: string | undefined | null): string {
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

  function authorLine(s: CommunityStory): string {
    if (s.is_global) return "Official";
    return `By ${s.author}`;
  }

  async function loadCommunity() {
    loading = true;
    loadError = null;
    try {
      const r = await fetch("/api/community", { credentials: "include" });
      const data = await r.json();
      if (!r.ok) {
        loadError =
          (data as { error?: string }).error ?? "Failed to load community";
        stories = [];
        return;
      }
      stories = (data as { stories?: CommunityStory[] }).stories ?? [];
    } catch {
      loadError = "Could not reach the server.";
      stories = [];
    } finally {
      loading = false;
    }
  }

  async function playStory(id: number) {
    busy = true;
    try {
      const r = await fetch("/api/adventures", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_content_id: id }),
      });
      if (r.status === 401) {
        goto("/login");
        return;
      }
      const data = await r.json();
      if (!r.ok) {
        loadError = (data as { error?: string }).error ?? "Could not start";
        return;
      }
      const adv = (data as { adventure?: { id: number } }).adventure;
      const aid = adv?.id;
      if (aid == null) {
        loadError = "Invalid response";
        return;
      }
      goto(`/play?adventure=${aid}`);
    } catch {
      loadError = "Start request failed";
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    void loadCommunity();
  });
</script>

<main class="wrap">
  {#if authState.checked && !authState.uid}
    <nav class="guest-nav" aria-label="Site">
      <a href="/">Lobby</a>
      <a href="/login">Log in</a>
    </nav>
  {/if}

  <header class="head">
    <h1>Community Stories</h1>
    <p class="sub">
      Browse stories created and shared by the community. Sign in to play.
    </p>
  </header>

  {#if loadError}
    <p class="err">{loadError}</p>
  {/if}

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if stories.length === 0}
    <section class="panel">
      <p class="muted">No public stories yet.</p>
    </section>
  {:else}
    <div class="catalog-grid">
      {#each stories as s (s.id)}
        <article class="story-card">
          <span class={genrePillClass(s.genre)}>
            {(s.genre ?? "").trim().replace(/-/g, " ") || "story"}
          </span>
          <h2 class="card-title">{s.title}</h2>
          <p class="card-desc">
            {(s.description ?? "").trim() ||
              "No description — jump in and see what happens."}
          </p>
          <p class="byline">{authorLine(s)}</p>
          <p class="play-stat">
            Played {s.play_count ?? 0}
            {(s.play_count ?? 0) === 1 ? "time" : "times"}
          </p>
          <button
            type="button"
            class="btn primary card-play"
            disabled={busy}
            onclick={() => playStory(s.id)}
          >
            {busy ? "Starting…" : "Play"}
          </button>
        </article>
      {/each}
    </div>
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
  .guest-nav {
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
    font-size: 0.9rem;
  }
  .guest-nav a {
    color: #8ab4f8;
    text-decoration: none;
  }
  .guest-nav a:hover {
    text-decoration: underline;
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
  .panel {
    padding: 1.25rem;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    border-radius: 10px;
  }
  .catalog-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
    gap: 1rem;
    margin-top: 0.5rem;
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
  .byline {
    margin: 0.55rem 0 0.15rem;
    font-size: 0.8rem;
    color: #bdc1c6;
  }
  .play-stat {
    margin: 0 0 0.5rem;
    font-size: 0.78rem;
    color: #9aa0a6;
  }
  .card-play {
    margin-top: auto;
    width: 100%;
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
  .err {
    color: #f28b82;
    font-size: 0.9rem;
  }
  .muted {
    color: #9aa0a6;
    font-size: 0.9rem;
  }
</style>
