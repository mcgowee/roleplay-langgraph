<script lang="ts">
  import { onMount, tick } from "svelte";
  import { goto } from "$app/navigation";
  import { get } from "svelte/store";
  import { page } from "$app/stores";
  import { NOTE_CATEGORIES, SAVE_SLOT_COUNT } from "$lib/constants";

  type PlayMessage = {
    role: "user" | "assistant" | "system";
    text: string;
  };

  let ready = $state(false);
  let adventureId = $state<number | null>(null);
  let slot = $state(0);
  let adventureName = $state<string | null>(null);
  let gameFile = $state<string | null>(null);
  let noSession = $state(false);

  let actionError = $state<string | null>(null);
  let actionOk = $state<string | null>(null);
  let messages = $state<PlayMessage[]>([]);
  let input = $state("");
  let sending = $state(false);

  let sidebarOpen = $state(true);
  let sidebarTab = $state<"actions" | "saves" | "feedback">("actions");

  let statusLoading = $state(false);
  let statusData = $state<Record<string, unknown> | null>(null);

  let slotsLoading = $state(false);
  let slotsData = $state<{ slots?: unknown[] } | null>(null);

  let feedbackCategory = $state<string>(NOTE_CATEGORIES[0]);
  let feedbackText = $state("");
  let feedbackBusy = $state(false);

  let paused = $state(false);
  let turnCount = $state(0);
  let currentLocation = $state<string | null>(null);

  let loadSlotInput = $state(0);
  let deleteSlotInput = $state(0);

  let logEl: HTMLDivElement | undefined = $state();

  const slotIndices = Array.from({ length: SAVE_SLOT_COUNT }, (_, i) => i);

  function historyToMessages(history: string[]): PlayMessage[] {
    const out: PlayMessage[] = [];
    for (const turn of history) {
      const nl = turn.indexOf("\n");
      if (nl === -1) {
        if (turn.startsWith("Player: ")) {
          out.push({ role: "user", text: turn.slice(8).trimEnd() });
        } else {
          out.push({ role: "assistant", text: turn });
        }
        continue;
      }
      const first = turn.slice(0, nl);
      const rest = turn.slice(nl + 1);
      if (first.startsWith("Player: ")) {
        out.push({ role: "user", text: first.slice(8).trimEnd() });
        out.push({ role: "assistant", text: rest });
      } else {
        out.push({ role: "assistant", text: turn });
      }
    }
    return out;
  }

  function messagesFromStatus(data: Record<string, unknown>): PlayMessage[] {
    const history = (data.history as string[]) ?? [];
    if (history.length > 0) return historyToMessages(history);
    const opening = data.empty_history_opening as string | undefined;
    if (opening?.trim()) return [{ role: "assistant", text: opening }];
    return [];
  }

  function toast(msg: string) {
    actionOk = msg;
    setTimeout(() => {
      actionOk = null;
    }, 3200);
  }

  function lastAssistantSnippet(): string {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant")
        return messages[i].text.slice(0, 3000);
    }
    return "";
  }

  function syncPlayUrl() {
    if (adventureId == null) return;
    goto(`/play?adventure=${adventureId}`, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
    });
  }

  function clearSession() {
    goto("/");
  }

  async function scrollToBottom() {
    await tick();
    if (logEl) logEl.scrollTop = logEl.scrollHeight;
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || adventureId == null || sending) return;
    input = "";
    messages = [...messages, { role: "user", text }];
    scrollToBottom();
    sending = true;
    actionError = null;
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          adventure_id: adventureId,
          message: text,
        }),
      });
      const data = await r.json();
      if (!r.ok || (data as { error?: string }).error) {
        messages = [
          ...messages,
          {
            role: "system",
            text: (data as { error?: string }).error ?? "Chat request failed",
          },
        ];
        return;
      }
      messages = [
        ...messages,
        {
          role: "assistant",
          text: (data as { response?: string }).response ?? "",
        },
      ];
      if (typeof (data as { turns?: number }).turns === "number") {
        turnCount = (data as { turns?: number }).turns!;
      }
      if (typeof (data as { location?: string }).location === "string") {
        currentLocation = (data as { location?: string }).location!;
      }
    } catch {
      messages = [
        ...messages,
        { role: "system", text: "Network error during chat" },
      ];
    } finally {
      sending = false;
      scrollToBottom();
    }
  }

  async function refreshStatus() {
    if (adventureId == null) return;
    statusLoading = true;
    actionError = null;
    try {
      const r = await fetch(
        `/api/status?adventure_id=${encodeURIComponent(String(adventureId))}`,
        { credentials: "include" }
      );
      const data = await r.json();
      if (!r.ok) {
        actionError = (data as { error?: string }).error ?? "Status failed";
        statusData = null;
        return;
      }
      statusData = data as Record<string, unknown>;
      const adv = data.adventure as
        | { name?: string; game_file?: string; active_slot?: number }
        | undefined;
      if (adv?.name) adventureName = adv.name;
      if (adv?.game_file) gameFile = adv.game_file;
      if (typeof adv?.active_slot === "number") slot = adv.active_slot;
      if ("paused" in (statusData ?? {})) {
        paused = !!(statusData as Record<string, unknown>).paused;
      }
      if (typeof (statusData as Record<string, unknown>)?.turns === "number") {
        turnCount = (statusData as Record<string, unknown>).turns as number;
      }
      if (typeof (statusData as Record<string, unknown>)?.location === "string") {
        currentLocation = (statusData as Record<string, unknown>).location as string;
      }
    } catch {
      actionError = "Status request failed";
    } finally {
      statusLoading = false;
    }
  }

  async function saveNow() {
    if (adventureId == null) return;
    actionError = null;
    try {
      const r = await fetch("/api/save", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ adventure_id: adventureId, slot }),
      });
      const data = await r.json();
      if (!r.ok) {
        actionError = (data as { error?: string }).error ?? "Save failed";
        return;
      }
      toast(`Saved to slot ${slot}.`);
    } catch {
      actionError = "Save request failed";
    }
  }

  async function resumeFromSlot() {
    if (adventureId == null) return;
    actionError = null;
    try {
      const r = await fetch("/api/resume", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          adventure_id: adventureId,
          slot: loadSlotInput,
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        actionError = (data as { error?: string }).error ?? "Load failed";
        return;
      }
      slot = loadSlotInput;
      syncPlayUrl();
      const r2 = await fetch(
        `/api/status?adventure_id=${encodeURIComponent(String(adventureId))}`,
        { credentials: "include" }
      );
      const d2 = await r2.json();
      if (r2.ok) {
        messages = messagesFromStatus(d2 as Record<string, unknown>);
      } else {
        messages = [
          {
            role: "system",
            text: `Loaded slot ${loadSlotInput} (${(data as { turns?: number }).turns ?? "?"} turns in save). Continue playing.`,
          },
        ];
      }
      await refreshStatus();
      toast(`Loaded slot ${loadSlotInput}.`);
    } catch {
      actionError = "Load request failed";
    }
  }

  async function fetchSlotList() {
    if (adventureId == null) return;
    slotsLoading = true;
    actionError = null;
    try {
      const r = await fetch(
        `/api/list_slots?adventure_id=${encodeURIComponent(String(adventureId))}`,
        { credentials: "include" }
      );
      const data = await r.json();
      if (!r.ok) {
        actionError = (data as { error?: string }).error ?? "List slots failed";
        slotsData = null;
        return;
      }
      slotsData = data as { slots?: unknown[] };
    } catch {
      actionError = "List slots failed";
    } finally {
      slotsLoading = false;
    }
  }

  async function deleteSaveSlot() {
    if (adventureId == null) return;
    if (
      !confirm(
        `Delete save slot ${deleteSlotInput} for this adventure? This cannot be undone.`
      )
    ) {
      return;
    }
    actionError = null;
    try {
      const r = await fetch("/api/delete_save", {
        method: "DELETE",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          adventure_id: adventureId,
          slot: deleteSlotInput,
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        actionError = (data as { error?: string }).error ?? "Delete failed";
        return;
      }
      toast(`Deleted slot ${deleteSlotInput}.`);
      await fetchSlotList();
    } catch {
      actionError = "Delete request failed";
    }
  }

  async function togglePause() {
    if (adventureId == null) return;
    actionError = null;
    const endpoint = paused ? "/api/unpause" : "/api/pause";
    try {
      const r = await fetch(endpoint, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ adventure_id: adventureId }),
      });
      const data = await r.json();
      if (!r.ok) {
        actionError =
          (data as { error?: string }).error ?? "Pause toggle failed";
        return;
      }
      paused = !paused;
      toast(paused ? "Game paused." : "Game resumed.");
    } catch {
      actionError = "Pause toggle failed";
    }
  }

  async function submitFeedback() {
    if (adventureId == null || !feedbackText.trim()) return;
    feedbackBusy = true;
    actionError = null;
    try {
      const r = await fetch("/api/feedback", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          adventure_id: adventureId,
          slot,
          game_file: gameFile,
          game_title: adventureName,
          category: feedbackCategory,
          text: feedbackText.trim(),
          last_response_snippet: lastAssistantSnippet(),
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        actionError = (data as { error?: string }).error ?? "Feedback failed";
        return;
      }
      feedbackText = "";
      toast("Feedback saved.");
    } catch {
      actionError = "Feedback request failed";
    } finally {
      feedbackBusy = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  onMount(() => {
    const u = get(page).url;
    const raw = u.searchParams.get("adventure");
    const id = raw != null && raw !== "" ? parseInt(raw, 10) : NaN;
    if (Number.isNaN(id) || id < 1) {
      noSession = true;
      ready = true;
      return;
    }

    adventureId = id;
    void (async () => {
      try {
        const r = await fetch(
          `/api/status?adventure_id=${encodeURIComponent(String(id))}`,
          { credentials: "include" }
        );
        const data = await r.json();
        if (!r.ok) {
          noSession = true;
          ready = true;
          return;
        }
        const d = data as Record<string, unknown>;
        messages = messagesFromStatus(d);
        const adv = d.adventure as
          | { name?: string; game_file?: string; active_slot?: number }
          | undefined;
        adventureName = adv?.name ?? null;
        gameFile = adv?.game_file ?? null;
        if (typeof adv?.active_slot === "number") slot = adv.active_slot;
        paused = !!d.paused;
        statusData = d;
        if (typeof d.location === "string") currentLocation = d.location;
        syncPlayUrl();
        ready = true;
      } catch {
        noSession = true;
        ready = true;
      }
    })();
  });
</script>

{#if !ready}
  <div class="center-msg">
    <p class="muted">Loading adventure…</p>
  </div>
{:else if noSession}
  <div class="center-msg">
    <p class="muted">No adventure selected. Open one from the lobby.</p>
    <a href="/" class="btn primary link-btn">Go to Lobby</a>
  </div>
{:else}
  <div class="play-layout" class:sidebar-collapsed={!sidebarOpen}>
    <aside class="sidebar" class:collapsed={!sidebarOpen}>
      <div class="sidebar-header">
        <h2 class="sidebar-title">
          {adventureName ?? gameFile ?? "Adventure"}
        </h2>
        <p class="sidebar-meta">
          Slot {slot} · Turn {turnCount} · Adventure #{adventureId}
        </p>
        {#if currentLocation}
          <p class="sidebar-location">{currentLocation.replace(/_/g, " ")}</p>
        {/if}
      </div>

      <nav class="sidebar-tabs">
        <button
          class="tab-btn"
          class:active={sidebarTab === "actions"}
          onclick={() => (sidebarTab = "actions")}
        >Actions</button>
        <button
          class="tab-btn"
          class:active={sidebarTab === "saves"}
          onclick={() => {
            sidebarTab = "saves";
            fetchSlotList();
          }}
        >Saves</button>
        <button
          class="tab-btn"
          class:active={sidebarTab === "feedback"}
          onclick={() => (sidebarTab = "feedback")}
        >Notes</button>
      </nav>

      <div class="sidebar-body">
        {#if sidebarTab === "actions"}
          <div class="action-group">
            <button class="btn sidebar-btn" onclick={saveNow}>Save now</button>
            <button
              class="btn sidebar-btn"
              disabled={statusLoading}
              onclick={refreshStatus}
            >
              {statusLoading ? "Loading…" : "Refresh status"}
            </button>
            <button class="btn sidebar-btn" onclick={togglePause}>
              {paused ? "Resume game" : "Pause game"}
            </button>
            <button class="btn sidebar-btn danger" onclick={clearSession}>
              End session
            </button>
          </div>

          {#if statusData}
            <div class="status-block">
              <h3 class="section-label">Game status</h3>
              <dl class="status-dl">
                {#each Object.entries(statusData) as [k, v] (k)}
                  <dt>{k}</dt>
                  <dd>
                    <pre>{typeof v === "object" ? JSON.stringify(v, null, 2) : String(v)}</pre>
                  </dd>
                {/each}
              </dl>
            </div>
          {/if}
        {:else if sidebarTab === "saves"}
          <div class="action-group">
            <div class="save-row">
              <label class="field-label">
                Load slot
                <select bind:value={loadSlotInput} class="select">
                  {#each slotIndices as n (n)}
                    <option value={n}>{n}</option>
                  {/each}
                </select>
              </label>
              <button class="btn sm" onclick={resumeFromSlot}>Load</button>
            </div>

            <div class="save-row">
              <label class="field-label">
                Delete slot
                <select bind:value={deleteSlotInput} class="select">
                  {#each slotIndices as n (n)}
                    <option value={n}>{n}</option>
                  {/each}
                </select>
              </label>
              <button class="btn sm danger" onclick={deleteSaveSlot}>Delete</button>
            </div>
          </div>

          {#if slotsLoading}
            <p class="muted">Loading saves…</p>
          {:else if slotsData}
            <div class="slots-list">
              <h3 class="section-label">Saved slots</h3>
              {#if (slotsData.slots ?? []).length === 0}
                <p class="muted">No saves yet.</p>
              {:else}
                {#each slotsData.slots ?? [] as s}
                  <pre class="slot-json">{JSON.stringify(s, null, 2)}</pre>
                {/each}
              {/if}
            </div>
          {/if}
        {:else if sidebarTab === "feedback"}
          <div class="action-group">
            <label class="field-label">
              Category
              <select bind:value={feedbackCategory} class="select">
                {#each NOTE_CATEGORIES as c (c)}
                  <option value={c}>{c}</option>
                {/each}
              </select>
            </label>
            <textarea
              rows="4"
              class="textarea"
              placeholder="What worked, what confused you, ideas…"
              bind:value={feedbackText}
            ></textarea>
            <button
              class="btn primary sm"
              disabled={feedbackBusy || !feedbackText.trim()}
              onclick={submitFeedback}
            >
              {feedbackBusy ? "Sending…" : "Send note"}
            </button>
          </div>
        {/if}

        {#if actionOk}
          <p class="ok">{actionOk}</p>
        {/if}
        {#if actionError}
          <p class="err">{actionError}</p>
        {/if}
      </div>
    </aside>

    <main class="chat-main">
      <button
        class="sidebar-toggle"
        onclick={() => (sidebarOpen = !sidebarOpen)}
        aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
      >
        {sidebarOpen ? "\u25C0" : "\u25B6"}
      </button>

      <div class="log" bind:this={logEl}>
        {#each messages as m, i (i)}
          <div class="msg {m.role}">
            {#if m.role === "user"}
              <span class="tag">You</span>
            {:else if m.role === "assistant"}
              <span class="tag">Game</span>
            {:else}
              <span class="tag">System</span>
            {/if}
            <pre>{m.text}</pre>
          </div>
        {/each}
      </div>

      <div class="composer">
        <textarea
          rows="2"
          placeholder="What do you do?"
          bind:value={input}
          onkeydown={onKeydown}
          disabled={sending}
          class="textarea"
        ></textarea>
        <button
          type="button"
          class="btn primary send-btn"
          disabled={sending || !input.trim()}
          onclick={sendMessage}
        >
          {sending ? "…" : "Send"}
        </button>
      </div>
    </main>
  </div>
{/if}

<style>
  .play-layout {
    display: flex;
    height: calc(100vh - 42px);
    overflow: hidden;
  }

  .center-msg {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: calc(100vh - 42px);
    gap: 1rem;
  }

  .sidebar {
    width: 280px;
    min-width: 280px;
    background: #13151a;
    border-right: 1px solid #2a2f38;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    transition:
      min-width 0.2s,
      width 0.2s,
      opacity 0.2s;
  }
  .sidebar.collapsed {
    width: 0;
    min-width: 0;
    opacity: 0;
    pointer-events: none;
  }

  .sidebar-header {
    padding: 1rem 1rem 0.75rem;
    border-bottom: 1px solid #2a2f38;
  }
  .sidebar-title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: #e8eaed;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sidebar-meta {
    margin: 0.25rem 0 0;
    font-size: 0.75rem;
    color: #9aa0a6;
  }
  .sidebar-location {
    margin: 0.35rem 0 0;
    font-size: 0.8rem;
    color: #81c995;
    font-weight: 500;
    text-transform: capitalize;
  }

  .sidebar-tabs {
    display: flex;
    border-bottom: 1px solid #2a2f38;
  }
  .tab-btn {
    flex: 1;
    padding: 0.5rem 0.25rem;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: #9aa0a6;
    font-size: 0.8rem;
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s;
  }
  .tab-btn:hover {
    color: #e8eaed;
  }
  .tab-btn.active {
    color: #8ab4f8;
    border-bottom-color: #8ab4f8;
  }

  .sidebar-body {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem 1rem;
  }

  .action-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .sidebar-btn {
    width: 100%;
    text-align: left;
  }

  .section-label {
    margin: 1rem 0 0.4rem;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #9aa0a6;
  }

  .save-row {
    display: flex;
    align-items: flex-end;
    gap: 0.5rem;
  }

  .field-label {
    font-size: 0.8rem;
    color: #bdc1c6;
    display: block;
  }

  .status-block {
    margin-top: 0.5rem;
  }
  .status-dl {
    margin: 0;
    font-size: 0.75rem;
  }
  .status-dl dt {
    color: #9aa0a6;
    margin-top: 0.4rem;
  }
  .status-dl dd {
    margin: 0.1rem 0 0;
  }
  .status-dl pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 0.7rem;
  }

  .slots-list {
    margin-top: 0.5rem;
  }
  .slot-json {
    margin: 0.3rem 0;
    font-size: 0.7rem;
    white-space: pre-wrap;
    word-break: break-word;
    color: #bdc1c6;
    background: #0f1114;
    padding: 0.4rem;
    border-radius: 4px;
  }

  .chat-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    position: relative;
  }

  .sidebar-toggle {
    position: absolute;
    top: 0.5rem;
    left: 0.5rem;
    z-index: 10;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    color: #9aa0a6;
    width: 28px;
    height: 28px;
    border-radius: 6px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.65rem;
    transition: color 0.15s;
  }
  .sidebar-toggle:hover {
    color: #e8eaed;
  }

  .log {
    flex: 1;
    overflow-y: auto;
    padding: 1rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .msg {
    padding: 0.75rem;
    border-radius: 8px;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    max-width: 52rem;
  }
  .msg.user {
    border-left: 3px solid #1a73e8;
  }
  .msg.assistant {
    border-left: 3px solid #81c995;
  }
  .msg.system {
    border-left: 3px solid #f28b82;
  }
  .tag {
    display: block;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #9aa0a6;
    margin-bottom: 0.3rem;
  }
  .msg pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: inherit;
    font-size: 0.9rem;
    line-height: 1.45;
  }

  .composer {
    padding: 0.75rem 1.5rem;
    border-top: 1px solid #2a2f38;
    background: #13151a;
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
  }
  .composer .textarea {
    flex: 1;
  }
  .send-btn {
    padding: 0.5rem 1.25rem;
    white-space: nowrap;
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
    padding: 0.35rem 0.65rem;
    font-size: 0.8rem;
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
  .select {
    margin-left: 0.35rem;
    padding: 0.3rem 0.45rem;
    border-radius: 6px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    font-size: 0.8rem;
  }
  .textarea {
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    padding: 0.5rem 0.65rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    font-family: inherit;
    font-size: 0.9rem;
    resize: vertical;
  }
  .err {
    color: #f28b82;
    font-size: 0.8rem;
    margin-top: 0.5rem;
  }
  .ok {
    color: #81c995;
    font-size: 0.8rem;
    margin-top: 0.5rem;
  }
  .muted {
    color: #9aa0a6;
    font-size: 0.85rem;
  }
  .link-btn {
    display: inline-block;
    text-decoration: none;
    text-align: center;
  }
</style>
