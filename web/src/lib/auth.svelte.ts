import { browser } from "$app/environment";
import { goto } from "$app/navigation";

export const authState = $state({
  uid: null as string | null,
  checked: false,
});

export async function checkAuth(): Promise<void> {
  if (!browser) {
    authState.checked = true;
    return;
  }
  try {
    const r = await fetch("/api/me", { credentials: "include" });
    if (r.ok) {
      const d = (await r.json()) as { uid?: string };
      authState.uid = d.uid ?? null;
    } else {
      authState.uid = null;
    }
  } catch {
    authState.uid = null;
  } finally {
    authState.checked = true;
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/logout", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch {
    /* ignore */
  }
  authState.uid = null;
  await goto("/login");
}
