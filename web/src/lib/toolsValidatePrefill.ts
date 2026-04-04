const KEY = "rpg_tools_validate_prefill";

export function setValidatePrefill(json: string): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(KEY, json);
}

/** Returns pasted JSON once, then clears (so refresh does not re-apply). */
export function consumeValidatePrefill(): string | null {
  if (typeof sessionStorage === "undefined") return null;
  const v = sessionStorage.getItem(KEY);
  if (v) sessionStorage.removeItem(KEY);
  return v;
}
