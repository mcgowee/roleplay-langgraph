<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";

  type MyStory = {
    id: number;
    title: string;
    description: string | null;
    genre: string | null;
    is_public: boolean;
    source_id: number | null;
    play_count: number;
    original_author: string | null;
    created_at: string;
    updated_at: string;
  };

  let stories = $state<MyStory[]>([]);
  let loading = $state(true);
  let loadError = $state<string | null>(null);
  let busy = $state(false);
  let currentUid = $state<string | null>(null);

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

  async function loadMe() {
    try {
      const r = await fetch("/api/me", { credentials: "include" });
      if (!r.ok) return;
      const d = (await r.json()) as { uid?: string };
      currentUid = d.uid ?? null;
    } catch {
      currentUid = null;
    }
  }

  async function loadStories() {
    loading = true;
    loadError = null;
    try {
      const r = await fetch("/api/game-content", { credentials: "include" });
      const data = await r.json();
      if (!r.ok) {
        loadError =
          (data as { error?: string }).error ?? "Failed to load stories";
        stories = [];
        return;
      }
      stories = (data as { stories?: MyStory[] }).stories ?? [];
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

  async function togglePublish(id: number) {
    busy = true;
    loadError = null;
    try {
      const r = await fetch(`/api/game-content/${id}/publish`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = await r.json();
      if (!r.ok) {
        loadError =
          (data as { error?: string }).error ?? "Publish toggle failed";
        return;
      }
      await loadStories();
    } catch {
      loadError = "Publish request failed";
    } finally {
      busy = false;
    }
  }

  async function deleteStory(s: MyStory) {
    if (
      !confirm(
        `Delete “${s.title}”? This cannot be undone if no adventures use it.`
      )
    ) {
      return;
    }
    busy = true;
    loadError = null;
    try {
      const r = await fetch(`/api/game-content/${s.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      const data = await r.json();
      if (!r.ok) {
        loadError = (data as { error?: string }).error ?? "Delete failed";
        return;
      }
      await loadStories();
    } catch {
      loadError = "Delete request failed";
    } finally {
      busy = false;
    }
  }

  function showBasedOn(author: string | null): boolean {
    if (!author || !currentUid) return false;
    return author !== currentUid;
  }

  onMount(() => {
    void loadMe();
    void loadStories();
  });
</script>

<main class="wrap">
  <header class="head">
    <h1>My Stories</h1>
    <p class="sub">
      Create, edit, and share your own text adventures. Need format help? Try the
      <a href="/tools/story-draft">story draft tool</a>
      or review the game design prompt in the project repo.
    </p>
  </header>

  {#if loadError}
    <p class="err">{loadError}</p>
  {/if}

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if stories.length === 0}
    <section class="panel empty-panel">
      <p class="muted">You haven&apos;t created any stories yet.</p>
      <button
        type="button"
        class="btn primary"
        onclick={() => goto("/stories/create")}
      >
        Create your first story
      </button>
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
            {(s.description ?? "").trim() || "No description yet."}
          </p>
          <div class="badges-row">
            <span class:is-public={s.is_public} class="vis-badge">
              {s.is_public ? "Public" : "Private"}
            </span>
            {#if s.is_public}
              <span class="play-stat"
                >Played {s.play_count ?? 0}
                {(s.play_count ?? 0) === 1 ? "time" : "times"}</span
              >
            {/if}
          </div>
          {#if showBasedOn(s.original_author)}
            <p class="based-on">
              Based on a story by {s.original_author}
            </p>
          {/if}
          <div class="actions">
            <button
              type="button"
              class="btn primary"
              disabled={busy}
              onclick={() => playStory(s.id)}
            >
              Play
            </button>
            <button
              type="button"
              class="btn"
              disabled={busy}
              onclick={() => goto(`/stories/${s.id}/edit`)}
            >
              Edit
            </button>
            <button
              type="button"
              class="btn"
              disabled={busy}
              onclick={() => togglePublish(s.id)}
            >
              {s.is_public ? "Unpublish" : "Publish"}
            </button>
            <button
              type="button"
              class="btn danger sm"
              disabled={busy}
              onclick={() => deleteStory(s)}
            >
              Delete
            </button>
          </div>
        </article>
      {/each}
    </div>
  {/if}

  <div class="footer-create">
    <button
      type="button"
      class="btn primary lg"
      onclick={() => goto("/stories/create")}
    >
      Create New Story
    </button>
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
  .panel {
    padding: 1.25rem;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    border-radius: 10px;
  }
  .empty-panel {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
    margin-top: 0.5rem;
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
    font-size: 0.85rem;
    line-height: 1.45;
    color: #9aa0a6;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .badges-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.65rem;
  }
  .vis-badge {
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #9aa0a6;
  }
  .vis-badge.is-public {
    color: #81c995;
  }
  .play-stat {
    font-size: 0.78rem;
    color: #9aa0a6;
  }
  .based-on {
    margin: 0.5rem 0 0;
    font-size: 0.78rem;
    color: #8ab4f8;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-top: 0.85rem;
    width: 100%;
  }
  .footer-create {
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid #2a2f38;
  }
  .btn {
    cursor: pointer;
    border: 1px solid #3c4043;
    background: #2a2f38;
    color: #e8eaed;
    padding: 0.45rem 0.85rem;
    border-radius: 8px;
    font-size: 0.85rem;
  }
  .btn.sm {
    padding: 0.3rem 0.55rem;
    font-size: 0.78rem;
  }
  .btn.lg {
    padding: 0.6rem 1.35rem;
    font-size: 1rem;
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
  .err {
    color: #f28b82;
    font-size: 0.9rem;
  }
  .muted {
    color: #9aa0a6;
    font-size: 0.9rem;
  }
</style>
