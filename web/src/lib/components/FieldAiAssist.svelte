<script lang="ts">
  type StoryTextField =
    | "opening"
    | "description"
    | "narrator_style"
    | "player_background"
    | "location_description"
    | "character_prompt"
    | "character_first_line";

  let {
    value = $bindable(""),
    field,
    disabled = false,
  }: {
    value: string;
    field: StoryTextField;
    disabled?: boolean;
  } = $props();

  let guideOpen = $state(false);
  let guideNote = $state("");
  let busy = $state(false);
  let localErr = $state<string | null>(null);
  let lastPromptUsed = $state<string | null>(null);
  let promptDetailOpen = $state(false);

  let canRun = $derived(!disabled && !busy && value.trim().length > 0);

  async function run(instruction: string) {
    localErr = null;
    busy = true;
    lastPromptUsed = null;
    promptDetailOpen = false;
    try {
      const r = await fetch("/api/improve-story-text", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          field,
          text: value,
          instruction: instruction.trim(),
        }),
      });
      const data = (await r.json()) as {
        text?: string;
        error?: string;
        prompt_used?: string;
      };
      if (!r.ok) {
        localErr = data.error ?? "Request failed";
        return;
      }
      const t = data.text;
      if (typeof t === "string" && t.length > 0) {
        value = t;
      }
      if (typeof data.prompt_used === "string" && data.prompt_used.length > 0) {
        lastPromptUsed = data.prompt_used;
      } else {
        lastPromptUsed = null;
      }
      guideOpen = false;
      guideNote = "";
    } catch {
      localErr = "Network error";
    } finally {
      busy = false;
    }
  }

  function polish() {
    void run("");
  }

  function toggleGuide() {
    guideOpen = !guideOpen;
    localErr = null;
  }

  function applyGuide() {
    void run(guideNote);
  }
</script>

<div class="field-ai">
  <div class="field-ai-row">
    <button
      type="button"
      class="ai-btn"
      disabled={!canRun}
      title="Rewrite with a general polish pass"
      onclick={polish}
    >
      {busy ? "…" : "Polish"}
    </button>
    <button
      type="button"
      class="ai-btn"
      disabled={disabled || busy || !value.trim()}
      title="Add instructions, then rewrite"
      onclick={toggleGuide}
    >
      {guideOpen ? "Hide guide" : "Guide…"}
    </button>
  </div>
  {#if guideOpen}
    <div class="guide-box">
      <textarea
        class="guide-input"
        rows="2"
        maxlength="1500"
        bind:value={guideNote}
        placeholder="e.g. Shorter, more noir, mention the storm…"
        disabled={disabled || busy}
      ></textarea>
      <button
        type="button"
        class="ai-btn primary"
        disabled={disabled || busy || !value.trim()}
        onclick={applyGuide}
      >
        {busy ? "…" : "Rewrite with guide"}
      </button>
    </div>
  {/if}
  {#if localErr}
    <p class="ai-err">{localErr}</p>
  {/if}
  {#if lastPromptUsed}
    <details class="ai-prompt-details" bind:open={promptDetailOpen}>
      <summary class="ai-prompt-summary">View AI prompt</summary>
      <pre class="ai-prompt-pre">{lastPromptUsed}</pre>
    </details>
  {/if}
</div>

<style>
  .field-ai {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.35rem;
    max-width: min(100%, 20rem);
  }
  .field-ai-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    justify-content: flex-end;
  }
  .ai-btn {
    cursor: pointer;
    border: 1px solid #3c4043;
    background: transparent;
    color: #8ab4f8;
    padding: 0.2rem 0.5rem;
    border-radius: 6px;
    font-size: 0.72rem;
    font-weight: 500;
  }
  .ai-btn:hover:not(:disabled) {
    background: rgba(138, 180, 248, 0.12);
    border-color: #5f6368;
  }
  .ai-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .ai-btn.primary {
    background: rgba(26, 115, 232, 0.25);
    border-color: #1a73e8;
    color: #8ab4f8;
  }
  .guide-box {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    align-items: stretch;
  }
  .guide-input {
    width: 100%;
    box-sizing: border-box;
    padding: 0.4rem 0.5rem;
    border-radius: 6px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    font-family: inherit;
    font-size: 0.8rem;
    line-height: 1.4;
    resize: vertical;
  }
  .guide-input:disabled {
    opacity: 0.6;
  }
  .ai-err {
    margin: 0;
    font-size: 0.72rem;
    color: #f28b82;
    text-align: right;
    line-height: 1.3;
  }
  .ai-prompt-details {
    width: 100%;
    margin-top: 0.25rem;
    text-align: left;
  }
  .ai-prompt-summary {
    cursor: pointer;
    font-size: 0.7rem;
    color: #6f747a;
    list-style: none;
  }
  .ai-prompt-summary::-webkit-details-marker {
    display: none;
  }
  .ai-prompt-summary::before {
    content: "▸ ";
    display: inline-block;
    transition: transform 0.15s ease;
    color: #5f6368;
  }
  details[open] > .ai-prompt-summary::before {
    transform: rotate(90deg);
  }
  .ai-prompt-pre {
    margin: 0.35rem 0 0;
    padding: 0.45rem 0.5rem;
    max-height: 12rem;
    overflow: auto;
    font-size: 0.68rem;
    line-height: 1.35;
    color: #80868b;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid #2a2f38;
    border-radius: 6px;
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
