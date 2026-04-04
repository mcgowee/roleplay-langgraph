import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export type PyResult = {
  code: number;
  stdout: string;
  stderr: string;
};

/**
 * Run a command with timeout (ms). Uses python3 on PATH.
 */
export async function runCommand(
  cmd: string,
  args: string[],
  options: { cwd: string; timeout?: number }
): Promise<PyResult> {
  const timeout = options.timeout ?? 120_000;
  try {
    const { stdout, stderr } = await execFileAsync(cmd, args, {
      cwd: options.cwd,
      encoding: "utf-8",
      maxBuffer: 20 * 1024 * 1024,
      timeout,
    });
    return { code: 0, stdout: stdout ?? "", stderr: stderr ?? "" };
  } catch (e: unknown) {
    const err = e as {
      code?: number;
      stdout?: string;
      stderr?: string;
      signal?: string;
    };
    return {
      code: typeof err.code === "number" ? err.code : 1,
      stdout: err.stdout ?? "",
      stderr: err.stderr ?? String(e),
    };
  }
}
