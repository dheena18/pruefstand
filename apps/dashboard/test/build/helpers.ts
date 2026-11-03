import { spawn, spawnSync } from "node:child_process";
import path from "node:path";

export const APP = path.resolve(__dirname, "../..");
export const SCRIPTS = path.resolve(APP, "../../scripts/dashboard");

export function node(script: string, args: string[], env: Record<string, string> = {}) {
  const result = spawnSync(process.execPath, [path.join(SCRIPTS, script), ...args], {
    encoding: "utf8",
    env: { ...process.env, ...env },
  });
  return { code: result.status, out: `${result.stdout}${result.stderr}` };
}

/** Async: a build takes a minute and a blocked worker misses Vitest's RPC heartbeat. */
export function buildSet(
  set: "populated" | "empty",
  out?: string,
  env: Record<string, string> = {},
): Promise<{ code: number | null; out: string }> {
  const args = [set, ...(out === undefined ? [] : ["--out", out])];
  return new Promise((resolve) => {
    const child = spawn(path.join(SCRIPTS, "build_set.sh"), args, {
      env: { ...process.env, ...env },
    });
    let text = "";
    child.stdout.on("data", (chunk: Buffer) => (text += chunk.toString()));
    child.stderr.on("data", (chunk: Buffer) => (text += chunk.toString()));
    child.on("close", (code) => resolve({ code, out: text }));
  });
}
