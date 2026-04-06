<script lang="ts">
  import { onMount } from "svelte";

  type GraphMeta = {
    name: string;
    description: string;
    node_count: number;
  };

  type GraphDefinition = {
    name: string;
    description: string;
    nodes: string[];
    entry_point: { router: string; mapping: Record<string, string> };
    edges: { from: string; to: string }[];
    conditional_edges: {
      from: string;
      router: string;
      mapping: Record<string, string>;
    }[];
  };

  let graphsMeta = $state<GraphMeta[]>([]);
  let registryNodes = $state<string[]>([]);
  let registryRouters = $state<string[]>([]);
  let catalogLoadError = $state<string | null>(null);

  let selectedGraphName = $state("");
  let isNew = $state(false);

  let name = $state("");
  let description = $state("");
  let selectedNodes = $state<string[]>([]);
  let entryRouter = $state("");
  let entryMappingRows = $state<{ k: string; v: string }[]>([{ k: "", v: "" }]);
  let edgeRows = $state<{ from: string; to: string }[]>([{ from: "", to: "" }]);
  let condEdgeRows = $state<
    { from: string; router: string; mappingRows: { k: string; v: string }[] }[]
  >([]);

  let actionBusy = $state(false);
  let actionMsg = $state<string | null>(null);
  let actionOk = $state(false);

  const nodeOptionsForDropdown = $derived(
    [...selectedNodes].sort((a, b) => a.localeCompare(b)),
  );
  const toOptions = $derived([...nodeOptionsForDropdown, "__end__"]);

  function toggleNode(node: string, checked: boolean) {
    if (checked) {
      if (!selectedNodes.includes(node)) selectedNodes = [...selectedNodes, node];
    } else {
      selectedNodes = selectedNodes.filter((n) => n !== node);
    }
  }

  function buildDefinition(): GraphDefinition {
    const entry_mapping: Record<string, string> = {};
    for (const row of entryMappingRows) {
      const k = row.k.trim();
      if (k) entry_mapping[k] = row.v.trim();
    }
    const edges = edgeRows
      .filter((e) => e.from && e.to)
      .map((e) => ({ from: e.from, to: e.to }));
    const conditional_edges = condEdgeRows
      .filter((ce) => ce.from && ce.router)
      .map((ce) => {
        const m: Record<string, string> = {};
        for (const r of ce.mappingRows) {
          const k = r.k.trim();
          if (k) m[k] = r.v.trim();
        }
        return { from: ce.from, router: ce.router, mapping: m };
      });
    return {
      name: name.trim(),
      description: description.trim(),
      nodes: [...selectedNodes].sort((a, b) => a.localeCompare(b)),
      entry_point: { router: entryRouter, mapping: entry_mapping },
      edges,
      conditional_edges,
    };
  }

  const jsonPreview = $derived.by(() => {
    try {
      return JSON.stringify(buildDefinition(), null, 2);
    } catch {
      return "{}";
    }
  });

  function applyDefinition(def: GraphDefinition) {
    name = def.name;
    description = typeof def.description === "string" ? def.description : "";
    selectedNodes = Array.isArray(def.nodes) ? [...def.nodes] : [];
    entryRouter = def.entry_point?.router ?? "";
    const em = def.entry_point?.mapping ?? {};
    const emEntries = Object.entries(em);
    entryMappingRows =
      emEntries.length > 0
        ? emEntries.map(([k, v]) => ({ k, v: String(v) }))
        : [{ k: "", v: "" }];
    const eds = def.edges ?? [];
    edgeRows =
      eds.length > 0
        ? eds.map((e) => ({ from: e.from, to: e.to }))
        : [{ from: "", to: "" }];
    const ces = def.conditional_edges ?? [];
    condEdgeRows = ces.map((ce) => ({
      from: ce.from,
      router: ce.router,
      mappingRows:
        Object.keys(ce.mapping ?? {}).length > 0
          ? Object.entries(ce.mapping).map(([k, v]) => ({ k, v: String(v) }))
          : [{ k: "", v: "" }],
    }));
  }

  function blankForm() {
    name = "";
    description = "";
    selectedNodes = [];
    entryRouter = registryRouters[0] ?? "";
    entryMappingRows = [{ k: "", v: "" }];
    edgeRows = [{ from: "", to: "" }];
    condEdgeRows = [];
    isNew = true;
    selectedGraphName = "";
    actionMsg = null;
  }

  async function loadCatalog() {
    catalogLoadError = null;
    try {
      const [gr, reg] = await Promise.all([
        fetch("/api/graphs", { credentials: "include" }),
        fetch("/api/graph-registry", { credentials: "include" }),
      ]);
      if (!gr.ok) throw new Error(`Graphs list: ${gr.status}`);
      if (!reg.ok) throw new Error(`Registry: ${reg.status}`);
      const gList = await gr.json();
      const r = await reg.json();
      graphsMeta = Array.isArray(gList) ? gList : [];
      registryNodes = Array.isArray(r.nodes) ? r.nodes : [];
      registryRouters = Array.isArray(r.routers) ? r.routers : [];
      if (!entryRouter && registryRouters.length) entryRouter = registryRouters[0];
    } catch (e) {
      catalogLoadError = e instanceof Error ? e.message : String(e);
    }
  }

  async function loadGraph(graphName: string) {
    actionMsg = null;
    try {
      const r = await fetch(
        `/api/graphs/${encodeURIComponent(graphName)}`,
        { credentials: "include" },
      );
      if (!r.ok) {
        actionMsg = `Failed to load graph: ${r.status}`;
        actionOk = false;
        return;
      }
      const def = (await r.json()) as GraphDefinition;
      applyDefinition(def);
      isNew = false;
      selectedGraphName = def.name;
    } catch {
      actionMsg = "Network error loading graph.";
      actionOk = false;
    }
  }

  function onSelectGraph() {
    const v = selectedGraphName;
    if (!v) {
      blankForm();
      return;
    }
    void loadGraph(v);
  }

  async function saveGraph() {
    const def = buildDefinition();
    if (!def.name.trim()) {
      actionMsg = "Name is required.";
      actionOk = false;
      return;
    }
    actionBusy = true;
    actionMsg = null;
    try {
      const isNewGraph = isNew;
      const url = isNewGraph
        ? "/api/graphs"
        : `/api/graphs/${encodeURIComponent(def.name)}`;
      const r = await fetch(url, {
        method: isNewGraph ? "POST" : "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(def),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        actionMsg = (data as { error?: string }).error ?? `Save failed (${r.status})`;
        actionOk = false;
        return;
      }
      actionMsg = isNewGraph ? "Graph created." : "Graph saved.";
      actionOk = true;
      await loadCatalog();
      isNew = false;
      selectedGraphName = def.name;
    } catch {
      actionMsg = "Network error while saving.";
      actionOk = false;
    } finally {
      actionBusy = false;
    }
  }

  async function deleteGraph() {
    const n = name.trim();
    if (!n || n === "standard") return;
    if (!confirm(`Delete graph "${n}"? This cannot be undone.`)) return;
    actionBusy = true;
    actionMsg = null;
    try {
      const r = await fetch(`/api/graphs/${encodeURIComponent(n)}`, {
        method: "DELETE",
        credentials: "include",
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        actionMsg = (data as { error?: string }).error ?? `Delete failed (${r.status})`;
        actionOk = false;
        return;
      }
      actionMsg = "Graph deleted.";
      actionOk = true;
      await loadCatalog();
      blankForm();
    } catch {
      actionMsg = "Network error while deleting.";
      actionOk = false;
    } finally {
      actionBusy = false;
    }
  }

  onMount(() => {
    void (async () => {
      await loadCatalog();
      blankForm();
    })();
  });
</script>

<section class="panel">
  <h2>Graph editor</h2>
  <p class="helper-text">
    Edit LangGraph pipeline templates used for <code>graph_type</code> in game JSON.
    Changes are saved to <code>graphs/*.json</code> on the server and reload the compiled
    graph in memory.
  </p>

  {#if catalogLoadError}
    <p class="msg bad">{catalogLoadError}</p>
  {/if}

  <div class="graph-toolbar">
    <label class="row block">
      <span class="lbl">Graph</span>
      <select
        class="inp wide"
        bind:value={selectedGraphName}
        onchange={onSelectGraph}
      >
        <option value="">— New graph —</option>
        {#each graphsMeta as g (g.name)}
          <option value={g.name}>{g.name} ({g.node_count} nodes)</option>
        {/each}
      </select>
    </label>
    <button type="button" class="btn" onclick={blankForm}>New graph</button>
  </div>

  {#if actionMsg}
    <p class="msg" class:good={actionOk} class:bad={!actionOk}>{actionMsg}</p>
  {/if}

  <div class="graph-card">
  <div class="graph-section">
    <h3 class="sub">Name</h3>
    <input
      type="text"
      class="inp wide"
      bind:value={name}
      disabled={!isNew}
      placeholder="e.g. standard"
      autocomplete="off"
    />
  </div>

  <div class="graph-section">
    <h3 class="sub">Description</h3>
    <input
      type="text"
      class="inp wide"
      bind:value={description}
      placeholder="Short description"
      autocomplete="off"
    />
  </div>

  <div class="graph-section">
    <h3 class="sub">Nodes</h3>
    <p class="helper-text">
      Include which pipeline nodes this graph uses. Edges must only reference included nodes.
    </p>
    <div class="node-grid">
      {#each registryNodes as node (node)}
        <label class="chk">
          <input
            type="checkbox"
            checked={selectedNodes.includes(node)}
            onchange={(e) =>
              toggleNode(node, (e.currentTarget as HTMLInputElement).checked)}
          />
          {node}
        </label>
      {/each}
    </div>
  </div>

  <div class="graph-section">
    <h3 class="sub">Entry point</h3>
    <label class="row block">
      <span class="lbl">Router</span>
      <select class="inp wide" bind:value={entryRouter}>
        {#each registryRouters as r (r)}
          <option value={r}>{r}</option>
        {/each}
      </select>
    </label>
    <p class="helper-text">Mapping: router return value → first node to run.</p>
    <div class="map-header" aria-hidden="true">
      <span>Router returns</span>
      <span class="map-header-mid"></span>
      <span>Goes to node</span>
    </div>
    {#each entryMappingRows as row, i (i)}
      <div class="map-row">
        <input
          type="text"
          class="inp"
          placeholder="Router returns"
          bind:value={row.k}
        />
        <span class="arrow">→</span>
        <select class="inp" bind:value={row.v} aria-label="Goes to node">
          <option value="">— node —</option>
          {#each nodeOptionsForDropdown as n (n)}
            <option value={n}>{n}</option>
          {/each}
        </select>
        <button
          type="button"
          class="btn sm"
          onclick={() => {
            entryMappingRows = entryMappingRows.filter((_, j) => j !== i);
            if (entryMappingRows.length === 0)
              entryMappingRows = [{ k: "", v: "" }];
          }}>Remove</button
        >
      </div>
    {/each}
    <button
      type="button"
      class="btn"
      onclick={() => {
        entryMappingRows = [...entryMappingRows, { k: "", v: "" }];
      }}>Add mapping row</button
    >
  </div>

  <div class="graph-section">
    <h3 class="sub">Unconditional edges</h3>
    <p class="helper-text">Static edges between nodes. Use <code>__end__</code> to end the run.</p>
    {#each edgeRows as row, i (i)}
      <div class="map-row">
        <select class="inp" bind:value={row.from}>
          <option value="">— from —</option>
          {#each nodeOptionsForDropdown as n (n)}
            <option value={n}>{n}</option>
          {/each}
        </select>
        <span class="arrow">→</span>
        <select class="inp" bind:value={row.to}>
          <option value="">— to —</option>
          {#each toOptions as t (t)}
            <option value={t}>{t}</option>
          {/each}
        </select>
        <button
          type="button"
          class="btn sm"
          onclick={() => {
            edgeRows = edgeRows.filter((_, j) => j !== i);
            if (edgeRows.length === 0) edgeRows = [{ from: "", to: "" }];
          }}>Remove</button
        >
      </div>
    {/each}
    <button
      type="button"
      class="btn"
      onclick={() => {
        edgeRows = [...edgeRows, { from: "", to: "" }];
      }}>Add edge</button
    >
  </div>

  <div class="graph-section">
    <h3 class="sub">Conditional edges</h3>
    <p class="helper-text">
      One block per source node that uses a router to choose the next step.
    </p>
    {#each condEdgeRows as ce, ci (ci)}
      <div class="cond-card">
        <div class="map-row">
          <label class="inline">
            From
            <select
              class="inp"
              value={ce.from}
              onchange={(e) => {
                const v = (e.currentTarget as HTMLSelectElement).value;
                condEdgeRows = condEdgeRows.map((c, j) =>
                  j === ci ? { ...c, from: v } : c,
                );
              }}
            >
              <option value="">— from —</option>
              {#each nodeOptionsForDropdown as n (n)}
                <option value={n}>{n}</option>
              {/each}
            </select>
          </label>
          <label class="inline">
            Router
            <select
              class="inp"
              value={ce.router}
              onchange={(e) => {
                const v = (e.currentTarget as HTMLSelectElement).value;
                condEdgeRows = condEdgeRows.map((c, j) =>
                  j === ci ? { ...c, router: v } : c,
                );
              }}
            >
              <option value="">— router —</option>
              {#each registryRouters as r (r)}
                <option value={r}>{r}</option>
              {/each}
            </select>
          </label>
          <button
            type="button"
            class="btn sm danger"
            onclick={() => {
              condEdgeRows = condEdgeRows.filter((_, j) => j !== ci);
            }}>Remove edge</button
          >
        </div>
        <div class="nested">
          <div class="map-header small" aria-hidden="true">
            <span>Router returns</span>
            <span class="map-header-mid"></span>
            <span>Goes to</span>
          </div>
          {#each ce.mappingRows as mr, mi (mi)}
            <div class="map-row">
              <input
                type="text"
                class="inp"
                placeholder="Router returns"
                value={mr.k}
                oninput={(e) => {
                  const keyVal = (e.currentTarget as HTMLInputElement).value;
                  condEdgeRows = condEdgeRows.map((c, j) =>
                    j !== ci
                      ? c
                      : {
                          ...c,
                          mappingRows: c.mappingRows.map((x, k) =>
                            k === mi ? { ...x, k: keyVal } : x,
                          ),
                        },
                  );
                }}
              />
              <span class="arrow">→</span>
              <select
                class="inp"
                value={mr.v}
                aria-label="Goes to"
                onchange={(e) => {
                  const toVal = (e.currentTarget as HTMLSelectElement).value;
                  condEdgeRows = condEdgeRows.map((c, j) =>
                    j !== ci
                      ? c
                      : {
                          ...c,
                          mappingRows: c.mappingRows.map((x, k) =>
                            k === mi ? { ...x, v: toVal } : x,
                          ),
                        },
                  );
                }}
              >
                <option value="">— to —</option>
                {#each toOptions as t (t)}
                  <option value={t}>{t}</option>
                {/each}
              </select>
              <button
                type="button"
                class="btn sm"
                onclick={() => {
                  condEdgeRows = condEdgeRows.map((c, j) => {
                    if (j !== ci) return c;
                    const mappingRows = c.mappingRows.filter((_, k) => k !== mi);
                    return {
                      ...c,
                      mappingRows:
                        mappingRows.length > 0
                          ? mappingRows
                          : [{ k: "", v: "" }],
                    };
                  });
                }}>Remove</button
              >
            </div>
          {/each}
          <button
            type="button"
            class="btn"
            onclick={() => {
              condEdgeRows = condEdgeRows.map((c, j) =>
                j === ci
                  ? { ...c, mappingRows: [...c.mappingRows, { k: "", v: "" }] }
                  : c,
              );
            }}>Add mapping row</button
          >
        </div>
      </div>
    {/each}
    <button
      type="button"
      class="btn"
      onclick={() => {
        condEdgeRows = [
          ...condEdgeRows,
          {
            from: "",
            router: "",
            mappingRows: [{ k: "", v: "" }],
          },
        ];
      }}>Add conditional edge</button
    >
  </div>

  <div class="graph-section">
    <h3 class="sub">JSON preview</h3>
    <textarea class="mono preview" readonly rows="14">{jsonPreview}</textarea>
  </div>

  <div class="row-actions">
    <button
      type="button"
      class="btn primary"
      disabled={actionBusy || !name.trim()}
      onclick={saveGraph}
    >
      {actionBusy ? "Saving…" : "Save"}
    </button>
    <button
      type="button"
      class="btn danger"
      disabled={actionBusy || !name.trim() || name.trim() === "standard" || isNew}
      onclick={deleteGraph}
    >
      Delete
    </button>
  </div>
  </div>
</section>

<style>
  .graph-card {
    margin-top: 0.75rem;
    padding: 1rem 1.25rem;
    background: #13151a;
    border: 1px solid #2a2f38;
    border-radius: 10px;
  }
  .graph-card > .graph-section:first-child {
    margin-top: 0;
    padding-top: 0;
    border-top: none;
  }
  .map-header {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.35rem;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
  }
  .map-header.small {
    margin-top: 0.25rem;
    margin-bottom: 0.25rem;
  }
  .map-header-mid {
    width: 1.25rem;
  }
  .graph-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }
  .graph-toolbar .row {
    flex: 1;
    min-width: 12rem;
  }
  .lbl {
    display: block;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #888;
    margin-bottom: 0.25rem;
  }
  .graph-section {
    margin-top: 1.25rem;
    padding-top: 1rem;
    border-top: 1px solid #2a2f38;
  }
  .sub {
    margin: 0 0 0.5rem;
    font-size: 0.95rem;
    font-weight: 600;
    color: #e8eaed;
  }
  .node-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
  }
  .chk {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.88rem;
    color: #bdc1c6;
    cursor: pointer;
  }
  .map-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }
  .arrow {
    color: #9aa0a6;
    font-size: 0.9rem;
  }
  .nested {
    margin-left: 0.75rem;
    padding-left: 0.75rem;
    border-left: 2px solid #3c4043;
    margin-top: 0.5rem;
  }
  .cond-card {
    background: #13151a;
    border: 1px solid #2a2f38;
    border-radius: 8px;
    padding: 0.75rem;
    margin-bottom: 0.75rem;
  }
  .inline {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    font-size: 0.75rem;
    color: #9aa0a6;
  }
  .preview {
    width: 100%;
    box-sizing: border-box;
    resize: vertical;
  }
  .msg {
    margin: 0.5rem 0;
    padding: 0.5rem 0.65rem;
    border-radius: 8px;
    font-size: 0.85rem;
  }
  .msg.good {
    background: rgba(129, 201, 149, 0.12);
    border: 1px solid #81c99544;
    color: #81c995;
  }
  .msg.bad {
    background: rgba(242, 139, 130, 0.12);
    border: 1px solid #f28b8244;
    color: #f6aea8;
  }
  :global(.tools-layout .btn.sm) {
    padding: 0.25rem 0.5rem;
    font-size: 0.8rem;
  }
  :global(.tools-layout .btn.danger) {
    border-color: #c5221f;
    color: #f6aea8;
    background: #3c1f1e;
  }
  :global(.tools-layout .btn.danger:disabled) {
    opacity: 0.4;
  }
</style>
