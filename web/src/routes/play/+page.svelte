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
  /** True when status/chat failed because the user is not logged in. */
  let authRequired = $state(false);

  let actionError = $state<string | null>(null);
  let actionOk = $state<string | null>(null);
  let messages = $state<PlayMessage[]>([]);
  let input = $state("");
  let sending = $state(false);

  let sidebarOpen = $state(true);
  let sidebarTab = $state<"status" | "actions" | "saves" | "feedback">(
    "status"
  );

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
  let milestones = $state<string[]>([]);
  let milestoneProgress = $state(0);
  let currentMilestone = $state<string | null>(null);
  let tensionMood = $state("progressing");
  let tensionTurns = $state(0);
  let npcTension = $state<Record<string, string>>({});

  let loadSlotInput = $state(0);
  let deleteSlotInput = $state(0);

  let logEl: HTMLDivElement | undefined = $state();

  const slotIndices = Array.from({ length: SAVE_SLOT_COUNT }, (_, i) => i);

  const friendlyStatusLabels: Record<string, string> = {
    inventory: "Inventory",
    inventory_weight: "Carrying",
    moods: "NPC Moods",
    turns: "Turns Played",
    location: "Current Location",
    paused: "Game Paused",
    milestones: "Milestones",
    milestone_progress: "Milestone Progress",
    current_milestone: "Current Goal",
    tension_mood: "Tension Mood",
    tension_turns_since_milestone: "Turns Since Milestone",
    npc_tension: "NPC Tension",
    graph_type: "Story Type",
    models: "AI Models",
    save_slots: "Save Slots",
  };

  function friendlyStatusKey(k: string): string {
    return friendlyStatusLabels[k] ?? k.replace(/_/g, " ");
  }

  /** Display name for an NPC key (underscores → spaces, title case). */
  function titleCaseNpcName(raw: string): string {
    return raw
      .replace(/_/g, " ")
      .split(/\s+/)
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(" ");
  }

  /** Title-case graph_type for sidebar (e.g. social → Social). */
  function friendlyGraphTypeLabel(raw: string): string {
    return raw
      .trim()
      .split(/[_\s]+/)
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(" ");
  }

  /** Compact line for a save slot from /api/list_slots, or null if shape is unknown. */
  function saveSlotSummaryLine(s: unknown): string | null {
    if (!s || typeof s !== "object") return null;
    const o = s as Record<string, unknown>;
    if (typeof o.slot !== "number") return null;
    const turns =
      typeof o.turn_count === "number"
        ? o.turn_count
        : typeof o.turns === "number"
          ? o.turns
          : "?";
    const locRaw =
      typeof o.location === "string" && o.location.trim() ? o.location : null;
    const loc = locRaw ? locRaw.replace(/_/g, " ") : "unknown";
    return `Slot ${o.slot}: Turn ${turns}, at ${loc}`;
  }

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
      const d = data as {
        turns?: number;
        location?: string;
        moods?: Record<string, number>;
        inventory?: string[];
        milestones?: string[];
        milestone_progress?: number;
        current_milestone?: string | null;
        tension_mood?: string;
        tension_turns_since_milestone?: number;
        npc_tension?: Record<string, string>;
        graph_type?: string;
      };
      if (typeof d.turns === "number") {
        turnCount = d.turns;
      }
      if (typeof d.location === "string") {
        currentLocation = d.location;
      }
      if (Array.isArray(d.milestones)) {
        milestones = d.milestones;
      }
      if (typeof d.milestone_progress === "number") {
        milestoneProgress = d.milestone_progress;
      }
      if (d.current_milestone !== undefined) {
        currentMilestone = d.current_milestone;
      }
      if (typeof d.tension_mood === "string") {
        tensionMood = d.tension_mood;
      }
      if (typeof d.tension_turns_since_milestone === "number") {
        tensionTurns = d.tension_turns_since_milestone;
      }
      if (d.npc_tension && typeof d.npc_tension === "object") {
        npcTension = d.npc_tension;
      }
      if (statusData) {
        const inv = Array.isArray(d.inventory) ? d.inventory : null;
        const next: Record<string, unknown> = {
          ...statusData,
          ...(typeof d.turns === "number" ? { turns: d.turns } : {}),
          ...(typeof d.location === "string" ? { location: d.location } : {}),
          ...(d.moods && typeof d.moods === "object" ? { moods: d.moods } : {}),
          ...(inv ? { inventory: inv } : {}),
          ...(typeof d.graph_type === "string"
            ? { graph_type: d.graph_type }
            : {}),
          ...(typeof d.tension_mood === "string"
            ? { tension_mood: d.tension_mood }
            : {}),
          ...(typeof d.tension_turns_since_milestone === "number"
            ? { tension_turns_since_milestone: d.tension_turns_since_milestone }
            : {}),
          ...(d.npc_tension && typeof d.npc_tension === "object"
            ? { npc_tension: d.npc_tension }
            : {}),
        };
        if (inv) {
          const iw = String(
            (statusData as { inventory_weight?: string }).inventory_weight ??
              "0/10"
          );
          const limit = iw.includes("/") ? iw.split("/")[1] : "10";
          next.inventory_weight = `${inv.length}/${limit}`;
        }
        statusData = next;
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
      const sd = statusData as Record<string, unknown>;
      if (Array.isArray(sd?.milestones)) {
        milestones = sd.milestones as string[];
      }
      if (typeof sd?.milestone_progress === "number") {
        milestoneProgress = sd.milestone_progress as number;
      }
      if (sd?.current_milestone !== undefined) {
        currentMilestone = sd.current_milestone as string | null;
      }
      if (typeof sd?.tension_mood === "string") {
        tensionMood = sd.tension_mood as string;
      }
      if (typeof sd?.tension_turns_since_milestone === "number") {
        tensionTurns = sd.tension_turns_since_milestone as number;
      }
      if (sd?.npc_tension && typeof sd.npc_tension === "object") {
        npcTension = sd.npc_tension as Record<string, string>;
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
      authRequired = false;
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
          authRequired = r.status === 401;
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
        if (Array.isArray(d.milestones)) milestones = d.milestones as string[];
        if (typeof d.milestone_progress === "number") milestoneProgress = d.milestone_progress as number;
        if (d.current_milestone !== undefined) currentMilestone = d.current_milestone as string | null;
        if (typeof d.tension_mood === "string") tensionMood = d.tension_mood as string;
        if (typeof d.tension_turns_since_milestone === "number")
          tensionTurns = d.tension_turns_since_milestone as number;
        if (d.npc_tension && typeof d.npc_tension === "object")
          npcTension = d.npc_tension as Record<string, string>;
        syncPlayUrl();
        ready = true;
      } catch {
        noSession = true;
        authRequired = false;
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
    {#if authRequired}
      <p class="muted">Sign in to open this adventure.</p>
      <a
        href="/login?redirect={encodeURIComponent(
          adventureId != null ? `/play?adventure=${adventureId}` : '/play'
        )}"
        class="btn primary link-btn"
      >
        Log in
      </a>
      <a href="/" class="btn link-btn subtle-outline">Lobby</a>
    {:else}
      <p class="muted">
        No adventure selected. Pick a story from the lobby, or continue a saved
        run after you log in.
      </p>
      <a href="/" class="btn primary link-btn">Go to Lobby</a>
    {/if}
  </div>
{:else}
  <div class="play-layout" class:sidebar-collapsed={!sidebarOpen}>
    <aside class="sidebar" class:collapsed={!sidebarOpen}>
      <div class="sidebar-header">
        <h2 class="sidebar-title">
          {adventureName ?? gameFile ?? "Adventure"}
        </h2>
        <p class="sidebar-meta">
          Save {slot} · Turn {turnCount} · Adventure #{adventureId}{#if statusData != null && typeof statusData.graph_type === "string"}
            · Type: <span class="graph-inline">{friendlyGraphTypeLabel(statusData.graph_type)}</span>{/if}
        </p>
        {#if currentLocation}
          <p class="sidebar-location">{currentLocation.replace(/_/g, " ")}</p>
        {/if}
      </div>

      <nav class="sidebar-tabs">
        <button
          class="tab-btn"
          class:active={sidebarTab === "status"}
          onclick={() => (sidebarTab = "status")}
        >Status</button>
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
        {#if sidebarTab === "status"}
          <div class="status-block">
            <h3 class="section-label section-label-tight">Game status</h3>
            <p class="muted status-tab-hint">
              Milestones and raw fields from the server. Use
              <strong>Actions</strong> → Refresh status to update.
            </p>

            {#if milestones.length > 0}
              <div class="sidebar-milestones status-tab-milestones">
                <p class="milestones-label">Milestones</p>
                <ul class="milestones-list">
                  {#each milestones as ms, i}
                    <li
                      class="milestone-item"
                      class:completed={i < milestoneProgress}
                      class:current={i === milestoneProgress}
                    >
                      <span class="milestone-icon"
                        >{i < milestoneProgress
                          ? "\u2713"
                          : i === milestoneProgress
                            ? "\u25B6"
                            : "\u25CB"}</span
                      >
                      {ms}
                    </li>
                  {/each}
                </ul>
              </div>

              <div class="sidebar-tension status-tab-tension">
                <p class="milestones-label">Tension</p>
                <p class="tension-mood-line">
                  <span
                    class="tension-state"
                    class:tension-prog={tensionMood === "progressing"}
                    class:tension-stall={tensionMood === "stalling"}
                    >{tensionMood === "stalling" ? "Stalling" : "Progressing"}</span
                  >
                  <span class="tension-turns-note"
                    > · {tensionTurns} turn{tensionTurns === 1 ? "" : "s"}</span
                  >
                </p>
                {#each Object.entries(npcTension) as [npcKey, desc] (npcKey)}
                  <div class="tension-npc-block">
                    <p class="tension-npc-label">{titleCaseNpcName(npcKey)}</p>
                    <p
                      class="tension-npc-desc"
                      class:tension-prog={tensionMood === "progressing"}
                      class:tension-stall={tensionMood === "stalling"}
                    >
                      {desc}
                    </p>
                  </div>
                {/each}
              </div>
            {/if}

            {#if statusData}
              <details class="status-json-details">
                <summary class="status-json-summary"
                  >Raw server state (all fields)</summary
                >
                <div class="status-json-inner">
                  <p class="helper-text">
                    Live game state from the server. Use Refresh Status to update.
                  </p>
                  <dl class="status-dl">
                    {#each Object.entries(statusData) as [k, v] (k)}
                      <dt>{friendlyStatusKey(k)}</dt>
                      <dd>
                        <pre>{typeof v === "object"
                          ? JSON.stringify(v, null, 2)
                          : String(v)}</pre>
                      </dd>
                    {/each}
                  </dl>
                </div>
              </details>
            {:else}
              <p class="muted status-tab-hint">
                No status loaded yet. Open <strong>Actions</strong> and use
                Refresh status.
              </p>
            {/if}
          </div>
        {:else if sidebarTab === "actions"}
          <p class="helper-text">
            Manage your session. Save your progress, refresh the game state, or
            pause to come back later.
          </p>
          <div class="action-group">
            <button
              class="btn sidebar-btn"
              title="Save your current progress to the active slot"
              onclick={saveNow}
            >Save now</button>
            <button
              class="btn sidebar-btn"
              disabled={statusLoading}
              title="Fetch the latest game state from the server"
              onclick={refreshStatus}
            >
              {statusLoading ? "Loading…" : "Refresh status"}
            </button>
            <button
              class="btn sidebar-btn"
              onclick={togglePause}
              title={paused
                ? "Unpause so the game processes your messages again"
                : "Pause the game — your messages won't be processed until you resume"}
            >
              {paused ? "Resume game" : "Pause game"}
            </button>
            <button
              class="btn sidebar-btn danger"
              title="Returns to the lobby. Your progress is auto-saved."
              onclick={clearSession}
            >
              End session
            </button>
          </div>
        {:else if sidebarTab === "saves"}
          <p class="helper-text">
            You have multiple save slots. Load a previous save to rewind, or
            delete ones you no longer need.
          </p>
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
              <button
                class="btn sm danger"
                title="Permanently delete this save slot"
                onclick={deleteSaveSlot}
              >Delete</button>
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
                  {@const slotLine = saveSlotSummaryLine(s)}
                  {#if slotLine}
                    <p class="slot-summary">{slotLine}</p>
                  {:else}
                    <details class="slot-details">
                      <summary>Slot data</summary>
                      <pre class="slot-json">{JSON.stringify(s, null, 2)}</pre>
                    </details>
                  {/if}
                {/each}
              {/if}
            </div>
          {/if}
        {:else if sidebarTab === "feedback"}
          <p class="helper-text">
            Leave notes for the developer about what worked, what was
            confusing, or ideas you have. These are stored with your adventure.
          </p>
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
          placeholder="What do you do? (press Enter to send)"
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
  .graph-inline {
    color: #bdc1c6;
    font-weight: 500;
  }
  .sidebar-location {
    margin: 0.35rem 0 0;
    font-size: 0.8rem;
    color: #81c995;
    font-weight: 500;
    text-transform: capitalize;
  }

  .sidebar-milestones {
    margin: 0.6rem 0 0;
    padding: 0.5rem 0.6rem;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 6px;
  }

  .status-tab-milestones {
    margin-top: 0;
    margin-bottom: 0.75rem;
  }

  .milestones-label {
    margin: 0 0 0.3rem;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #999;
  }

  .milestones-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .milestone-item {
    font-size: 0.78rem;
    padding: 0.15rem 0;
    color: #777;
  }

  .milestone-item.completed {
    color: #81c995;
    text-decoration: line-through;
  }

  .milestone-item.current {
    color: #e8eaed;
    font-weight: 500;
  }

  .milestone-icon {
    margin-right: 0.35rem;
  }

  .sidebar-tension {
    margin: 0.6rem 0 0;
    padding: 0.5rem 0.6rem;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 6px;
  }

  .status-tab-tension {
    margin-top: 0;
    margin-bottom: 0.75rem;
  }

  .tension-mood-line {
    margin: 0 0 0.45rem;
    font-size: 0.78rem;
    line-height: 1.4;
    color: #bdc1c6;
  }

  .tension-state {
    font-weight: 600;
  }

  .tension-state.tension-prog {
    color: #81c995;
  }

  .tension-state.tension-stall {
    color: #f6b93b;
  }

  .tension-turns-note {
    font-weight: 400;
    color: #9aa0a6;
  }

  .tension-npc-block {
    margin-top: 0.45rem;
  }

  .tension-npc-label {
    margin: 0 0 0.15rem;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
  }

  .tension-npc-desc {
    margin: 0;
    font-size: 0.76rem;
    line-height: 1.45;
    color: #bdc1c6;
  }

  .tension-npc-desc.tension-prog {
    color: #81c995;
  }

  .tension-npc-desc.tension-stall {
    color: #f6b93b;
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

  .helper-text {
    margin: 0 0 0.55rem;
    color: #9aa0a6;
    font-size: 0.82rem;
    line-height: 1.45;
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

  .section-label-tight {
    margin-top: 0;
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
    margin-top: 0;
  }
  .status-tab-hint {
    margin: 0 0 0.5rem;
    font-size: 0.72rem;
    line-height: 1.4;
  }

  .status-json-details {
    margin-top: 0.25rem;
    border: 1px solid #2a2f38;
    border-radius: 8px;
    overflow: hidden;
    background: #0f1114;
  }

  .status-json-summary {
    cursor: pointer;
    padding: 0.55rem 0.65rem;
    font-size: 0.78rem;
    font-weight: 600;
    color: #bdc1c6;
    background: #1a1d23;
    list-style: none;
    user-select: none;
  }

  .status-json-summary::-webkit-details-marker {
    display: none;
  }

  .status-json-details[open] .status-json-summary {
    border-bottom: 1px solid #2a2f38;
  }

  .status-json-inner {
    max-height: min(50vh, 22rem);
    overflow-y: auto;
    padding: 0.4rem 0.5rem 0.65rem;
  }

  .status-dl {
    margin: 0;
    font-size: 0.75rem;
  }
  .status-dl dt {
    color: #9aa0a6;
    margin-top: 0.4rem;
  }
  .status-dl dt:first-child {
    margin-top: 0;
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
  .slot-summary {
    margin: 0.35rem 0;
    font-size: 0.8rem;
    line-height: 1.4;
    color: #bdc1c6;
  }
  .slot-details {
    margin: 0.35rem 0;
    font-size: 0.78rem;
    color: #9aa0a6;
    border: 1px solid #2a2f38;
    border-radius: 6px;
    padding: 0.35rem 0.5rem;
    background: #13151a;
  }
  .slot-details summary {
    cursor: pointer;
    color: #bdc1c6;
    font-weight: 500;
    list-style: none;
  }
  .slot-details summary::-webkit-details-marker {
    display: none;
  }
  .slot-details .slot-json {
    margin-top: 0.45rem;
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
  .link-btn.subtle-outline {
    margin-left: 0.5rem;
    padding: 0.45rem 0.85rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    color: #bdc1c6;
    background: transparent;
  }
  .link-btn.subtle-outline:hover {
    border-color: #5f6368;
    color: #e8eaed;
  }
</style>
