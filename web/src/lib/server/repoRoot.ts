import path from "node:path";
import { existsSync } from "node:fs";
import { env } from "$env/dynamic/private";

/**
 * Absolute path to the roleplay-langgraph repo (directory containing `scripts/`).
 * Set `RPG_REPO_ROOT` in `web/.env` if auto-discovery from `process.cwd()` fails.
 */
export function repoRoot(): string {
  const fromEnv = env.RPG_REPO_ROOT?.trim();
  if (fromEnv) return path.resolve(fromEnv);

  let dir = process.cwd();
  for (let i = 0; i < 14; i++) {
    if (existsSync(path.join(dir, "scripts", "validate_game_json.py"))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }

  throw new Error(
    "Could not find repo root (scripts/validate_game_json.py). Run `npm run dev` from the `web/` folder inside the repo, or set RPG_REPO_ROOT in web/.env."
  );
}
