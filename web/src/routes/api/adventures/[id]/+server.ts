import type { RequestHandler } from "./$types";
import { proxyFlaskText } from "$lib/server/flask";

export const DELETE: RequestHandler = async ({ request, params }) => {
  const id = params.id;
  if (!id) {
    return new Response(JSON.stringify({ error: "missing id" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  return proxyFlaskText(request, `/adventures/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
};
