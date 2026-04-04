<script lang="ts">
  import { goto } from "$app/navigation";
  import { setValidatePrefill } from "$lib/toolsValidatePrefill";

  let storyText = $state("");
  let storyModel = $state("");
  let storyBusy = $state(false);
  let storyResult = $state<{
    ok: boolean;
    stderr: string;
    gameJson: unknown;
    rawStdout?: string;
  } | null>(null);

  async function runStoryDraft() {
    storyBusy = true;
    storyResult = null;
    try {
      const r = await fetch("/api/tools/story_draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          story: storyText,
          model: storyModel.trim() || undefined,
        }),
      });
      const data = await r.json();
      storyResult = {
        ok: (data as { ok?: boolean }).ok ?? false,
        stderr: (data as { stderr?: string }).stderr ?? "",
        gameJson: (data as { gameJson?: unknown }).gameJson ?? null,
        rawStdout: (data as { rawStdout?: string }).rawStdout,
      };
    } catch {
      storyResult = {
        ok: false,
        stderr: "Network error",
        gameJson: null,
      };
    } finally {
      storyBusy = false;
    }
  }

  function validateDraftJson() {
    if (!storyResult?.gameJson) return;
    setValidatePrefill(JSON.stringify(storyResult.gameJson, null, 2));
    goto("/tools/validate");
  }

  function downloadDraft() {
    if (!storyResult?.gameJson) return;
    const blob = new Blob(
      [JSON.stringify(storyResult.gameJson, null, 2) + "\n"],
      { type: "application/json" }
    );
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "draft_game.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }
</script>

<section class="panel">
  <h2>Story → draft JSON (Ollama)</h2>
  <p class="hint">
    Runs <code>scripts/story_to_game_draft.py</code> with a temp file (can take several minutes).
    Then download JSON or open the <a href="/tools/validate">validator</a> with this draft.
  </p>
  <label class="row block">
    Model (optional, else server default from <code>config.py</code>)
    <input
      type="text"
      class="inp wide"
      placeholder="llama3.1:8b"
      bind:value={storyModel}
    />
  </label>
  <textarea
    class="mono"
    rows="14"
    placeholder="Paste your story or outline…"
    bind:value={storyText}
  ></textarea>
  <div class="row-actions">
    <button type="button" class="btn primary" disabled={storyBusy} onclick={runStoryDraft}>
      {storyBusy ? "Calling Ollama…" : "Generate draft"}
    </button>
    {#if storyResult?.gameJson}
      <button type="button" class="btn" onclick={downloadDraft}>Download JSON</button>
      <button type="button" class="btn" onclick={validateDraftJson}>Validate this draft</button>
    {/if}
  </div>
  {#if storyResult?.stderr}
    <pre class="out notes">{storyResult.stderr}</pre>
  {/if}
  {#if storyResult && !storyResult.ok && storyResult.rawStdout}
    <pre class="out bad">Raw output (parse failed):\n{storyResult.rawStdout}</pre>
  {/if}
</section>
