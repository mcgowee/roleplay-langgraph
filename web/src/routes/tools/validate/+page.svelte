<script lang="ts">
  import { onMount } from "svelte";
  import { consumeValidatePrefill } from "$lib/toolsValidatePrefill";

  let validateInput = $state("");
  let validateBusy = $state(false);
  let validateResult = $state<{ ok: boolean; output: string } | null>(null);

  onMount(() => {
    const pre = consumeValidatePrefill();
    if (pre) validateInput = pre;
  });

  async function runValidate() {
    validateBusy = true;
    validateResult = null;
    try {
      const r = await fetch("/api/tools/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: validateInput }),
      });
      const data = await r.json();
      if (!r.ok) {
        validateResult = {
          ok: false,
          output: (data as { error?: string }).error ?? "Request failed",
        };
        return;
      }
      validateResult = {
        ok: (data as { ok?: boolean }).ok ?? false,
        output: (data as { output?: string }).output ?? "",
      };
    } catch {
      validateResult = { ok: false, output: "Network error" };
    } finally {
      validateBusy = false;
    }
  }
</script>

<section class="panel">
  <h2>Validate game JSON</h2>
  <p class="hint">
    Paste a full game object (same shape as <code>games/*.json</code>). Runs
    <code>scripts/validate_game_json.py</code>.
  </p>
  <textarea
    class="mono"
    rows="12"
    placeholder={`{ "title": "…" }`}
    bind:value={validateInput}
  ></textarea>
  <button type="button" class="btn primary" disabled={validateBusy} onclick={runValidate}>
    {validateBusy ? "Running…" : "Validate"}
  </button>
  {#if validateResult}
    <pre class="out" class:bad={!validateResult.ok} class:good={validateResult.ok}>{validateResult.output}</pre>
  {/if}
</section>
