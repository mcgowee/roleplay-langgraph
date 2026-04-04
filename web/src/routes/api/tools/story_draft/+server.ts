import { json } from "@sveltejs/kit";
import { writeFile, unlink } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";
import type { RequestHandler } from "./$types";
import { repoRoot } from "$lib/server/repoRoot";
import { runCommand } from "$lib/server/runPython";

const DRAFT_TIMEOUT_MS = 600_000;

export const POST: RequestHandler = async ({ request }) => {
  let root: string;
  try {
    root = repoRoot();
  } catch {
    return json(
      {
        ok: false,
        stderr:
          "Could not find repo root. Set RPG_REPO_ROOT in web/.env or run dev from web/ inside the repo.",
      },
      { status: 500 }
    );
  }

  let body: { story?: string; model?: string };
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const story = (body.story ?? "").trim();
  if (!story) {
    return json({ error: "story text is required" }, { status: 400 });
  }
  const id = randomBytes(8).toString("hex");
  const storyPath = join(tmpdir(), `rpg-story-${id}.txt`);
  try {
    await writeFile(storyPath, story, "utf-8");
    const args = ["scripts/story_to_game_draft.py", storyPath, "--no-validate"];
    if (body.model?.trim()) {
      args.push("-m", body.model.trim());
    }
    const res = await runCommand("python3", args, {
      cwd: root,
      timeout: DRAFT_TIMEOUT_MS,
    });

    let gameJson: unknown = null;
    if (res.code === 0 && res.stdout.trim()) {
      try {
        const start = res.stdout.indexOf("{");
        const end = res.stdout.lastIndexOf("}");
        if (start !== -1 && end > start) {
          gameJson = JSON.parse(res.stdout.slice(start, end + 1));
        }
      } catch {
        /* leave null */
      }
    }

    return json({
      ok: res.code === 0 && gameJson != null,
      exitCode: res.code,
      stderr: res.stderr.trim(),
      gameJson,
      rawStdout: gameJson == null ? res.stdout.trim().slice(0, 50_000) : undefined,
    });
  } finally {
    try {
      await unlink(storyPath);
    } catch {
      /* ignore */
    }
  }
};
