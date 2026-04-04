<script lang="ts">
  import type { Snippet } from "svelte";
  import { browser } from "$app/environment";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { onMount } from "svelte";
  import { authState, checkAuth, logout } from "$lib/auth.svelte";

  let { children }: { children: Snippet } = $props();

  onMount(() => {
    void (async () => {
      await checkAuth();
      const path = $page.url.pathname;
      if (authState.uid && path === "/login") {
        await goto("/");
        return;
      }
      if (
        !authState.uid &&
        path !== "/login" &&
        !path.startsWith("/tools")
      ) {
        await goto("/login");
      }
    })();
  });

  let showNav = $derived(browser && authState.checked && authState.uid !== null);
  let bootLoading = $derived(browser && !authState.checked);
  let redirectHold = $derived(
    browser &&
      authState.checked &&
      !authState.uid &&
      $page.url.pathname !== "/login" &&
      !$page.url.pathname.startsWith("/tools")
  );
</script>

<svelte:head>
  <title>LangGraph RPG</title>
</svelte:head>

{#if bootLoading}
  <p class="boot">Loading…</p>
{:else if redirectHold}
  <p class="boot">Redirecting…</p>
{:else}
  {#if showNav}
    <nav class="site-nav">
      <div class="nav-left">
        <a href="/">Lobby</a>
        <a href="/play">Play</a>
        <a href="/tools">Tools</a>
      </div>
      <div class="nav-right">
        <span class="who">{authState.uid}</span>
        <button type="button" class="logout" onclick={() => logout()}>Log out</button>
      </div>
    </nav>
  {/if}

  {@render children()}
{/if}

<style>
  .boot {
    margin: 0;
    padding: 2rem 1rem;
    text-align: center;
    color: #9aa0a6;
    font-size: 0.95rem;
    background: #0f1114;
    min-height: 100vh;
    box-sizing: border-box;
  }
  .site-nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.65rem 1rem;
    background: #13151a;
    border-bottom: 1px solid #2a2f38;
  }
  .nav-left {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .nav-right {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 0.85rem;
    color: #9aa0a6;
  }
  .who {
    max-width: 12rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .logout {
    cursor: pointer;
    border: 1px solid #3c4043;
    background: #2a2f38;
    color: #e8eaed;
    padding: 0.35rem 0.65rem;
    border-radius: 6px;
    font-size: 0.8rem;
  }
  .logout:hover {
    border-color: #5f6368;
  }
  .site-nav a {
    color: #8ab4f8;
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 500;
  }
  .site-nav a:hover {
    text-decoration: underline;
  }
  :global(body) {
    margin: 0;
    font-family:
      system-ui,
      -apple-system,
      Segoe UI,
      Roboto,
      sans-serif;
    background: #0f1114;
    color: #e8eaed;
    min-height: 100vh;
  }
</style>
