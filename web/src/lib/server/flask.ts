import { env } from "$env/dynamic/private";

/** Base URL for the LangGraph RPG Flask app (server-side only). */
export function flaskBase(): string {
  const u = env.FLASK_API_URL?.trim();
  if (u) return u.replace(/\/$/, "");
  return "http://127.0.0.1:5051";
}

function relaySetCookies(from: Response, to: Headers): void {
  const anyHeaders = from.headers as unknown as {
    getSetCookie?: () => string[];
  };
  if (typeof anyHeaders.getSetCookie === "function") {
    for (const c of anyHeaders.getSetCookie()) {
      to.append("Set-Cookie", c);
    }
    return;
  }
  const single = from.headers.get("set-cookie");
  if (single) {
    to.append("Set-Cookie", single);
  }
}

/**
 * Proxy to Flask, forwarding the browser Cookie header and relaying Set-Cookie back.
 */
export async function proxyFlask(
  request: Request,
  path: string,
  init?: RequestInit
): Promise<Response> {
  const url = `${flaskBase()}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init?.headers);
  if (init?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const cookie = request.headers.get("cookie");
  if (cookie) {
    headers.set("Cookie", cookie);
  }

  const upstream = await fetch(url, { ...init, headers });

  const out = new Headers();
  const ct = upstream.headers.get("content-type");
  if (ct) {
    out.set("Content-Type", ct);
  }
  relaySetCookies(upstream, out);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: out,
  });
}

/**
 * Read upstream as text (for JSON endpoints) while preserving Set-Cookie headers.
 */
export async function proxyFlaskText(
  request: Request,
  path: string,
  init?: RequestInit
): Promise<Response> {
  const upstream = await proxyFlask(request, path, init);
  const text = await upstream.text();
  // Carry over all headers (including Set-Cookie) from the already-built response
  const out = new Headers(upstream.headers);
  return new Response(text, { status: upstream.status, headers: out });
}
