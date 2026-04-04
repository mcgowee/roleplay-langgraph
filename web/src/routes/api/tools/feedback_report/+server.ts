import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { repoRoot } from "$lib/server/repoRoot";
import { runCommand } from "$lib/server/runPython";

export const GET: RequestHandler = async ({ url }) => {
  let root: string;
  try {
    root = repoRoot();
  } catch {
    return json(
      {
        ok: false,
        exitCode: 1,
        text: "Could not find repo root. Set RPG_REPO_ROOT in web/.env or run dev from web/ inside the repo.",
      },
      { status: 500 }
    );
  }

  const brief = url.searchParams.get("brief") === "1" || url.searchParams.get("brief") === "true";
  const game = url.searchParams.get("game")?.trim();
  const args = ["scripts/feedback_report.py"];
  if (brief) args.push("--brief");
  if (game) args.push("--game", game);

  const res = await runCommand("python3", args, { cwd: root, timeout: 30_000 });
  return json({
    ok: res.code === 0,
    exitCode: res.code,
    text: (res.stdout + (res.stderr ? "\n" + res.stderr : "")).trim(),
  });
};
