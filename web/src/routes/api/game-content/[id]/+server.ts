import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { proxyFlaskText } from "$lib/server/flask";

export const GET: RequestHandler = async ({ request, params }) => {
  return proxyFlaskText(request, `/game-content/${params.id}`, { method: "GET" });
};

export const PUT: RequestHandler = async ({ request, params }) => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON body" }, { status: 400 });
  }
  return proxyFlaskText(request, `/game-content/${params.id}`, {
    method: "PUT",
    body: JSON.stringify(body ?? {}),
  });
};

export const DELETE: RequestHandler = async ({ request, params }) => {
  return proxyFlaskText(request, `/game-content/${params.id}`, {
    method: "DELETE",
  });
};
