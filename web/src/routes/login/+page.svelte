<script lang="ts">
  import { goto } from "$app/navigation";
  import { authState } from "$lib/auth.svelte";

  let mode = $state<"login" | "register">("login");
  let uid = $state("");
  let password = $state("");
  let busy = $state(false);
  let err = $state<string | null>(null);

  async function submit() {
    err = null;
    const u = uid.trim();
    if (!u || !password) {
      err = "Enter username and password.";
      return;
    }
    busy = true;
    try {
      const path = mode === "login" ? "/api/login" : "/api/register";
      const r = await fetch(path, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uid: u, password }),
      });
      const data = (await r.json()) as { uid?: string; error?: string };
      if (!r.ok) {
        err =
          data.error ??
          (r.status === 409
            ? "Username already taken"
            : r.status === 401
              ? "Wrong username or password"
              : "Request failed");
        return;
      }
      authState.uid = data.uid ?? u;
      await goto("/");
    } catch {
      err = "Network error";
    } finally {
      busy = false;
    }
  }
</script>

<div class="auth-wrap">
  <div class="card">
    <h1>{mode === "login" ? "Log in" : "Create account"}</h1>

    {#if err}
      <p class="err">{err}</p>
    {/if}

    <label class="field">
      Username
      <input
        class="inp"
        type="text"
        autocomplete="username"
        bind:value={uid}
      />
    </label>
    <label class="field">
      Password
      <input
        class="inp"
        type="password"
        autocomplete={mode === "login" ? "current-password" : "new-password"}
        bind:value={password}
      />
    </label>

    <button
      type="button"
      class="btn primary"
      disabled={busy}
      onclick={submit}
    >
      {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
    </button>

    <p class="switch">
      {#if mode === "login"}
        <button type="button" class="linkish" onclick={() => (mode = "register")}>
          Need an account? Register
        </button>
      {:else}
        <button type="button" class="linkish" onclick={() => (mode = "login")}>
          Already have an account? Log in
        </button>
      {/if}
    </p>
  </div>
</div>

<style>
  .auth-wrap {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
    background: #0f1114;
  }
  .card {
    width: 100%;
    max-width: 22rem;
    padding: 1.5rem 1.75rem;
    background: #1a1d23;
    border: 1px solid #2a2f38;
    border-radius: 12px;
  }
  h1 {
    margin: 0 0 1rem;
    font-size: 1.25rem;
    font-weight: 600;
    color: #e8eaed;
  }
  .field {
    display: block;
    margin-bottom: 0.85rem;
    font-size: 0.85rem;
    color: #9aa0a6;
  }
  .inp {
    display: block;
    width: 100%;
    box-sizing: border-box;
    margin-top: 0.35rem;
    padding: 0.5rem 0.65rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #0f1114;
    color: #e8eaed;
    font-size: 0.95rem;
  }
  .btn {
    width: 100%;
    margin-top: 0.5rem;
    padding: 0.55rem 1rem;
    border-radius: 8px;
    border: 1px solid #3c4043;
    background: #2a2f38;
    color: #e8eaed;
    font-size: 0.95rem;
    cursor: pointer;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn.primary {
    background: #1a73e8;
    border-color: #1a73e8;
  }
  .err {
    color: #f28b82;
    font-size: 0.85rem;
    margin: 0 0 0.75rem;
  }
  .switch {
    margin: 1rem 0 0;
    text-align: center;
  }
  .linkish {
    background: none;
    border: none;
    color: #8ab4f8;
    cursor: pointer;
    font-size: 0.88rem;
    text-decoration: underline;
    padding: 0;
  }
</style>
