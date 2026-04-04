import { json } from "@sveltejs/kit";
import { writeFile, unlink } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";
import type { RequestHandler } from "./$types";
import { repoRoot } from "$lib/server/repoRoot";
import { runCommand } from "$lib/server/runPython";

export const POST: RequestHandler = async ({ request }) => {
  let root: string;
  try {
    root = repoRoot();
  } catch {
    return json(
      {
        error:
          "Could not find repo root. Run dev from repo `web/` folder or set RPG_REPO_ROOT in web/.env",
      },
      { status: 500 }
    );
  }

  let body: { content?: string };
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const content = (body.content ?? "").trim();
  if (!content) {
    return json({ error: "content (JSON string) is required" }, { status: 400 });
  }
  const tmp = join(tmpdir(), `rpg-validate-${randomBytes(8).toString("hex")}.json`);
  try {
    await writeFile(tmp, content, "utf-8");
    const res = await runCommand(
      "python3",
      ["scripts/validate_game_json.py", tmp],
      { cwd: root, timeout: 30_000 }
    );
    return json({
      ok: res.code === 0,
      exitCode: res.code,
      output: (res.stdout + "\n" + res.stderr).trim(),
    });
  } finally {
    try {
      await unlink(tmp);
    } catch {
      /* ignore */
    }
  }
};
