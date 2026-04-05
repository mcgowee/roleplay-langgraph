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

  let canRun = $derived(!disabled && !busy && value.trim().length > 0);

  async function run(instruction: string) {
    localErr = null;
    busy = true;
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
      const data = (await r.json()) as { text?: string; error?: string };
      if (!r.ok) {
        localErr = data.error ?? "Request failed";
        return;
      }
      const t = data.text;
      if (typeof t === "string" && t.length > 0) {
        value = t;
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
</style>
