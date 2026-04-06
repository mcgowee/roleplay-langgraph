import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { proxyFlaskText } from "$lib/server/flask";

function graphPath(name: string | undefined): string {
  const n = name ?? "";
  return `/graphs/${encodeURIComponent(n)}`;
}

export const GET: RequestHandler = async ({ request, params }) => {
  return proxyFlaskText(request, graphPath(params.name), { method: "GET" });
};

export const PUT: RequestHandler = async ({ request, params }) => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON body" }, { status: 400 });
  }
  return proxyFlaskText(request, graphPath(params.name), {
    method: "PUT",
    body: JSON.stringify(body ?? {}),
  });
};

export const DELETE: RequestHandler = async ({ request, params }) => {
  return proxyFlaskText(request, graphPath(params.name), {
    method: "DELETE",
  });
};
