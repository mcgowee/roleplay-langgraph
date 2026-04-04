import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { proxyFlaskText } from "$lib/server/flask";

export const GET: RequestHandler = async ({ request, url }) => {
  const adventureId = url.searchParams.get("adventure_id");
  if (!adventureId?.trim()) {
    return json({ error: "adventure_id query required" }, { status: 400 });
  }
  const q = new URLSearchParams({ adventure_id: adventureId });
  return proxyFlaskText(request, `/status?${q}`, { method: "GET" });
};
