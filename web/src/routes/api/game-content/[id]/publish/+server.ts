import type { RequestHandler } from "./$types";
import { proxyFlaskText } from "$lib/server/flask";

export const POST: RequestHandler = async ({ request, params }) => {
  return proxyFlaskText(request, `/game-content/${params.id}/publish`, {
    method: "POST",
    body: "{}",
  });
};
