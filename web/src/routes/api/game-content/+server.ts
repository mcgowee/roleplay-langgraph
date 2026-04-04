import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { proxyFlaskText } from "$lib/server/flask";

export const GET: RequestHandler = async ({ request }) => {
  return proxyFlaskText(request, "/game-content", { method: "GET" });
};

export const POST: RequestHandler = async ({ request }) => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON body" }, { status: 400 });
  }
  return proxyFlaskText(request, "/game-content", {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
};
