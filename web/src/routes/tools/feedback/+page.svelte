<script lang="ts">
  let feedbackBrief = $state(true);
  let feedbackGame = $state("");
  let feedbackBusy = $state(false);
  let feedbackText = $state("");

  async function runFeedbackReport() {
    feedbackBusy = true;
    feedbackText = "";
    try {
      const q = new URLSearchParams();
      if (feedbackBrief) q.set("brief", "1");
      if (feedbackGame.trim()) q.set("game", feedbackGame.trim());
      const r = await fetch(`/api/tools/feedback_report?${q}`);
      const data = await r.json();
      feedbackText = (data as { text?: string }).text ?? "";
    } catch {
      feedbackText = "Network error";
    } finally {
      feedbackBusy = false;
    }
  }
</script>

<section class="panel">
  <h2>Feedback report</h2>
  <p class="helper-text">
    View notes and feedback that players have left during play sessions.
  </p>
  <label class="row">
    <input type="checkbox" bind:checked={feedbackBrief} /> Brief (copy-paste friendly)
  </label>
  <label class="row">
    Filter by story name (optional)
    <input
      type="text"
      class="inp"
      placeholder="e.g. mayas_match"
      bind:value={feedbackGame}
    />
  </label>
  <button
    type="button"
    class="btn primary"
    disabled={feedbackBusy}
    onclick={runFeedbackReport}
  >
    {feedbackBusy ? "Running…" : "Generate report"}
  </button>
  {#if feedbackText}
    <pre class="out">{feedbackText}</pre>
  {/if}
</section>
