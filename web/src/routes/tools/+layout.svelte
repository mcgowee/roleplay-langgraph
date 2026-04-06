<script lang="ts">
  import type { Snippet } from "svelte";
  import { page } from "$app/stores";

  let { children }: { children: Snippet } = $props();

  const sub = [
    { href: "/tools", label: "Overview" },
    { href: "/tools/validate", label: "Validate JSON" },
    { href: "/tools/feedback", label: "Feedback report" },
    { href: "/tools/story-draft", label: "AI Story Generator" },
    { href: "/tools/graphs", label: "Graph Editor" },
  ];
</script>

<div class="tools-layout">
  <p class="lead">
    These call the same <strong>Python scripts</strong> as the CLI (server-side). Ollama must be
    running for <em>AI Story Generator</em>. If <code>npm run dev</code> is not started from the repo
    root, set <code>RPG_REPO_ROOT</code> in <code>web/.env</code>.
  </p>

  <nav class="tools-subnav" aria-label="Tools sections">
    {#each sub as { href, label }}
      <a href={href} class:active={$page.url.pathname === href}>{label}</a>
    {/each}
  </nav>

  {@render children()}
</div>

<style>
  .tools-layout {
    max-width: 46rem;
    margin: 0 auto;
    padding: 0 1rem 3rem;
  }
  .lead {
    color: #9aa0a6;
    font-size: 0.9rem;
    line-height: 1.5;
    margin-bottom: 1rem;
  }
  .lead code {
    background: #2a2f38;
    padding: 0.1rem 0.35rem;
    border-radius: 4px;
    font-size: 0.85em;
  }
  .tools-subnav {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    margin-bottom: 1.25rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid #2a2f38;
  }
  .tools-subnav a {
    color: #8ab4f8;
    text-decoration: none;
    font-size: 0.9rem;
  }
  .tools-subnav a:hover {
    text-decoration: underline;
  }
  .tools-subnav a.active {
    color: #e8eaed;
    font-weight: 600;
    text-decoration: none;
  }

  :global(.tools-layout .panel) {
    margin-top: 1.25rem;
    padding: 1rem 1.25rem;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    border-radius: 10px;
  }
  :global(.tools-layout .panel h2) {
    margin: 0 0 0.5rem;
    font-size: 1.05rem;
  }
  :global(.tools-layout .hint) {
    margin: 0 0 0.75rem;
    font-size: 0.85rem;
    color: #9aa0a6;
  }
  :global(.tools-layout .helper-text) {
    margin: 0 0 0.55rem;
    color: #9aa0a6;
    font-size: 0.82rem;
    line-height: 1.45;
  }
  :global(.tools-layout .helper-text.stderr-intro),
  :global(.tools-layout .helper-text.stdout-intro) {
    margin-top: 0.75rem;
  }
  :global(.tools-layout .mono) {
    width: 100%;
    box-sizing: border-box;
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    padding: 0.6rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    margin-bottom: 0.5rem;
  }
  :global(.tools-layout .btn) {
    cursor: pointer;
    border: 1px solid #3c4043;
    background: #2a2f38;
    color: #e8eaed;
    padding: 0.45rem 0.9rem;
    border-radius: 8px;
    font-size: 0.9rem;
  }
  :global(.tools-layout .btn:disabled) {
    opacity: 0.5;
    cursor: not-allowed;
  }
  :global(.tools-layout .btn.primary) {
    background: #1a73e8;
    border-color: #1a73e8;
  }
  :global(.tools-layout .out) {
    margin-top: 0.75rem;
    padding: 0.75rem;
    background: #13151a;
    border-radius: 8px;
    font-size: 0.8rem;
    white-space: pre-wrap;
    word-break: break-word;
    border: 1px solid #2a2f38;
  }
  :global(.tools-layout .out.good) {
    border-color: #81c99555;
  }
  :global(.tools-layout .out.bad) {
    border-color: #f28b8255;
  }
  :global(.tools-layout .out.notes) {
    color: #bdc1c6;
  }
  :global(.tools-layout .row) {
    display: block;
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
    color: #bdc1c6;
  }
  :global(.tools-layout .row.block) {
    margin-bottom: 0.75rem;
  }
  :global(.tools-layout .inp) {
    margin-left: 0.35rem;
    padding: 0.35rem 0.5rem;
    border-radius: 6px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
  }
  :global(.tools-layout .inp.wide) {
    display: block;
    width: 100%;
    max-width: 24rem;
    margin: 0.35rem 0 0;
    box-sizing: border-box;
  }
  :global(.tools-layout .row-actions) {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }

  :global(.tools-layout .hub-list) {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  :global(.tools-layout .hub-list li) {
    margin-bottom: 1rem;
  }
  :global(.tools-layout .hub-list a) {
    color: #8ab4f8;
    font-weight: 600;
    text-decoration: none;
  }
  :global(.tools-layout .hub-list a:hover) {
    text-decoration: underline;
  }
  :global(.tools-layout .hub-list p) {
    margin: 0.25rem 0 0;
    font-size: 0.88rem;
    color: #9aa0a6;
    line-height: 1.45;
  }
  :global(.tools-layout .hub-list p.helper-text) {
    margin-top: 0.35rem;
    font-size: 0.82rem;
    line-height: 1.45;
  }
  :global(.tools-layout .hub-list code) {
    background: #2a2f38;
    padding: 0.1rem 0.35rem;
    border-radius: 4px;
    font-size: 0.85em;
  }
  :global(.tools-layout .panel .hint a),
  :global(.tools-layout .panel .helper-text a) {
    color: #8ab4f8;
  }
</style>
