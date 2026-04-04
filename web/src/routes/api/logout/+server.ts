import type { RequestHandler } from "./$types";
import { proxyFlaskText } from "$lib/server/flask";

export const POST: RequestHandler = async ({ request }) => {
  return proxyFlaskText(request, "/logout", {
    method: "POST",
    body: "{}",
  });
};
