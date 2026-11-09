import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import type { RunIndexEntry } from "@/lib/types";

/** A data tree holding only `runs/index.json` with the given entries (enough for `generateStaticParams`). */
export async function dataWithIndex(runs: RunIndexEntry[]): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "dash-"));
  await mkdir(path.join(dir, "runs"), { recursive: true });
  await writeFile(
    path.join(dir, "runs", "index.json"),
    JSON.stringify({ schema_version: "1", runs }),
  );
  return dir;
}
