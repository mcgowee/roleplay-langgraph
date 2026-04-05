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
  <h2>AI Story Generator</h2>
  <p class="helper-text">
    Paste a story outline or concept below. The AI will generate locations,
    characters, and game structure from it. This usually takes 2-5 minutes.
    When it&apos;s done, download the JSON or send it to the
    <a href="/tools/validate">validator</a>.
  </p>
  <label class="row block">
    AI model (optional — leave blank for the default)
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
      {storyBusy ? "Generating… this may take a few minutes" : "Generate draft"}
    </button>
    {#if storyResult?.gameJson}
      <button type="button" class="btn" onclick={downloadDraft}>Download JSON</button>
      <button type="button" class="btn" onclick={validateDraftJson}>Validate this draft</button>
    {/if}
  </div>
  {#if storyResult?.stderr}
    <p class="helper-text stderr-intro">Processing log from the AI service:</p>
    <pre class="out notes">{storyResult.stderr}</pre>
  {/if}
  {#if storyResult && !storyResult.ok && storyResult.rawStdout}
    <p class="helper-text stdout-intro">
      The AI returned text that couldn&apos;t be converted to game JSON. You can try
      again or copy this output and manually format it:
    </p>
    <pre class="out bad">{storyResult.rawStdout}</pre>
  {/if}
</section>
