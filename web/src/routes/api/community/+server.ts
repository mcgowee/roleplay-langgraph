import type { RequestHandler } from "./$types";
import { proxyFlaskText } from "$lib/server/flask";

export const GET: RequestHandler = async ({ request }) => {
  return proxyFlaskText(request, "/community", { method: "GET" });
};
